import io
import pandas as pd
import streamlit as st

from claude_client import call_claude_json
from prompts import SYSTEM_SCAN, SYSTEM_EBIOS, REQUIRED_FIELDS, score_scenario

st.set_page_config(page_title="Formind — Outil EBIOS RM", page_icon="🛡️", layout="wide")

SECTEURS = [
    "Finance / Banque", "Santé", "Énergie / OIV", "Collectivité", "Industrie",
    "Tech / SaaS", "Transport", "Défense", "Assurance", "Retail", "Autre",
]
TAILLES = [
    "TPE (<50 sal.)", "PME (50-500 sal.)", "ETI (500-5000 sal.)",
    "GE (>5000 sal.)", "Administration", "OIV / OSE",
]
MAT_DIMS = [
    ("gov", "Gouvernance & Organisation"),
    ("risk", "Gestion des risques"),
    ("tech", "Protection technique"),
    ("inc", "Gestion des incidents"),
    ("conf", "Conformité & Audit"),
]
MAT_LABELS = {1: "Initial", 2: "Répété", 3: "Défini", 4: "Géré", 5: "Optimisé"}

defaults = {
    "step": 1,
    "nom": "", "secteur": SECTEURS[0], "secteur_autre": "",
    "taille": TAILLES[1], "perimetre": "",
    "reglements": [], "reglement_autre": "",
    "incidents": "", "menaces": "",
    "equipe_it": "", "equipe_sec": "", "prestataires": "", "projets_recents": "",
    "notes": "",
    "maturite": {k: 2 for k, _ in MAT_DIMS},
    "nb_scenarios": 7,
    "analysis": None,
    "scenarios": None,
    "scen_status": {},
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)


def build_context() -> str:
    m = st.session_state
    mat_str = ", ".join(
        f"{label}: {m['maturite'][k]}/5 ({MAT_LABELS[m['maturite'][k]]})"
        for k, label in MAT_DIMS
    )
    regs = list(m["reglements"]) + ([m["reglement_autre"]] if m["reglement_autre"] else [])
    return f"""Organisation: {m['nom']}
Secteur: {m['secteur_autre'] if m['secteur'] == 'Autre' else m['secteur']} | Taille: {m['taille']}
Périmètre & actifs: {m['perimetre'] or 'Non précisé'}
Réglementation: {', '.join(regs) or 'Non précisée'}
Incidents passés: {m['incidents'] or 'Aucun signalé'}
Menaces connues: {m['menaces'] or 'Aucune identifiée'}
Équipe IT: {m['equipe_it'] or '?'} | Équipe sécurité: {m['equipe_sec'] or '?'}
Prestataires: {m['prestataires'] or '?'}
Projets récents: {m['projets_recents'] or '?'}
Maturité SSI: {mat_str}
Notes consultant: {m['notes'] or 'Aucune'}"""


def export_excel(scenarios: list[dict]) -> bytes:
    df = pd.DataFrame(scenarios)
    df["statut"] = df["id"].map(lambda i: st.session_state["scen_status"].get(i, "pending"))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Scénarios EBIOS RM")
    return buf.getvalue()


st.title("🛡️ Formind — Outil consultant EBIOS RM")
cols = st.columns(3)
labels = ["1. Collecte du contexte", "2. Analyse de l'existant", "3. Scénarios EBIOS RM"]
for i, col in enumerate(cols, start=1):
    with col:
        marker = "✅" if st.session_state.step > i else ("▶️" if st.session_state.step == i else "⬜")
        st.markdown(f"**{marker} {labels[i - 1]}**")
st.divider()

if st.session_state.step == 1:
    st.subheader("📋 Collecte du contexte métier")

    c1, c2 = st.columns(2)
    st.session_state.nom = c1.text_input("Nom de l'organisation *", st.session_state.nom)
    st.session_state.taille = c2.selectbox("Taille", TAILLES, index=TAILLES.index(st.session_state.taille))
    st.session_state.secteur = st.selectbox("Secteur d'activité", SECTEURS, index=SECTEURS.index(st.session_state.secteur))
    if st.session_state.secteur == "Autre":
        st.session_state.secteur_autre = st.text_input("Précisez le secteur *", st.session_state.secteur_autre)
    st.session_state.perimetre = st.text_area(
        "Périmètre & actifs critiques *",
        st.session_state.perimetre,
        placeholder="ex: ERP, BDD clients, réseau interne, applications web exposées…",
    )

    st.session_state.reglements = st.multiselect(
        "Réglementation & conformité",
        ["RGPD", "NIS2", "HDS", "PCI-DSS", "ISO 27001", "RGS", "LPM", "DORA", "SOC 2"],
        default=st.session_state.reglements,
    )
    st.session_state.reglement_autre = st.text_input("Autres obligations spécifiques", st.session_state.reglement_autre)

    c1, c2 = st.columns(2)
    st.session_state.equipe_it = c1.text_input("Effectif équipe IT", st.session_state.equipe_it)
    st.session_state.equipe_sec = c2.text_input("Effectif équipe sécurité", st.session_state.equipe_sec)
    st.session_state.prestataires = st.text_input("Prestataires & sous-traitants", st.session_state.prestataires)
    st.session_state.projets_recents = st.text_input("Projets SI en cours ou récents", st.session_state.projets_recents)

    st.session_state.incidents = st.text_area("Incidents de sécurité passés", st.session_state.incidents)
    st.session_state.menaces = st.text_area("Menaces connues & sources de risque", st.session_state.menaces)

    st.markdown("**Évaluation de la maturité SSI** (1 = Initial → 5 = Optimisé)")
    for k, label in MAT_DIMS:
        st.session_state.maturite[k] = st.slider(label, 1, 5, st.session_state.maturite[k])

    st.session_state.nb_scenarios = st.selectbox("Nombre de scénarios à générer", [5, 7, 10, 12, 15], index=1)
    st.session_state.notes = st.text_input("Notes du consultant", st.session_state.notes)

    if st.button("✦ Analyser l'existant et passer à l'étape 2 →", type="primary", use_container_width=True):
        if not st.session_state.nom.strip() or not st.session_state.perimetre.strip():
            st.error("⚠ Veuillez renseigner au minimum le nom et le périmètre.")
        else:
            with st.spinner("Analyse du contexte en cours…"):
                try:
                    st.session_state.analysis = call_claude_json(
                        SYSTEM_SCAN, f"Analyse ce contexte:\n\n{build_context()}"
                    )
                    st.session_state.step = 2
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

elif st.session_state.step == 2:
    a = st.session_state.analysis
    st.subheader(f"🔍 Analyse de l'existant — {st.session_state.nom}")

    niveau_icon = {"Faible": "🔴", "Moyen": "🟡", "Satisfaisant": "🟢", "Bon": "✅"}.get(a["niveau_global"], "📊")
    st.info(f"{niveau_icon} **Niveau de maturité global : {a['niveau_global']}**\n\n{a['resume']}")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**✅ Points forts**")
        for f in a.get("forces", []):
            st.markdown(f"- {f}")
    with c2:
        st.markdown("**⚠️ Lacunes identifiées**")
        for g in a.get("gaps", []):
            st.markdown(f"- {g}")
    with c3:
        st.markdown("**🎯 Domaines prioritaires**")
        for p in a.get("priorites", []):
            st.markdown(f"- {p}")

    if a.get("recommandation"):
        st.warning(f"💡 **Recommandation avant l'analyse détaillée**\n\n{a['recommandation']}")

    c1, c2 = st.columns([1, 4])
    if c1.button("← Retour"):
        st.session_state.step = 1
        st.rerun()
    if c2.button(f"⚡ Générer {st.session_state.nb_scenarios} scénarios de risques →", type="primary", use_container_width=True):
        with st.spinner("Génération des scénarios EBIOS RM en cours…"):
            try:
                raw = call_claude_json(
                    SYSTEM_EBIOS,
                    f"Génère {st.session_state.nb_scenarios} scénarios EBIOS RM pour:\n\n{build_context()}",
                )
                if not isinstance(raw, list):
                    raise ValueError("Format de réponse inattendu (tableau attendu).")

                scenarios = []
                for i, s in enumerate(raw):
                    if not all(s.get(f) for f in REQUIRED_FIELDS):
                        continue
                    s = dict(s)
                    s["id"] = s.get("id") or f"SC-{i + 1:03d}"
                    s["score"] = score_scenario(s["vraisemblance"], s["gravite"])
                    scenarios.append(s)

                if not scenarios:
                    raise ValueError("Aucun scénario exploitable n'a pu être extrait. Réessayez la génération.")
                if len(scenarios) < len(raw):
                    st.toast(f"{len(raw) - len(scenarios)} scénario(s) incomplet(s) ignoré(s).", icon="⚠️")

                st.session_state.scenarios = scenarios
                st.session_state.scen_status = {s["id"]: "pending" for s in scenarios}
                st.session_state.step = 3
                st.rerun()
            except Exception as e:
                st.error(str(e))

elif st.session_state.step == 3:
    scenarios = st.session_state.scenarios or []
    st.subheader(f"🛡 Registre EBIOS RM — {st.session_state.nom}")
    st.caption(f"{len(scenarios)} scénarios générés · Validez, modifiez ou rejetez chaque scénario.")

    crit = sum(1 for s in scenarios if s["gravite"] == "Critique")
    val = sum(1 for v in st.session_state.scen_status.values() if v == "validated")
    pend = sum(1 for v in st.session_state.scen_status.values() if v == "pending")
    avg = round(sum(s["score"] for s in scenarios) / len(scenarios), 1) if scenarios else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total", len(scenarios))
    m2.metric("Critiques", crit)
    m3.metric("Validés", val)
    m4.metric("Score moyen", avg)

    c1, c2 = st.columns([1, 4])
    if c1.button("← Retour"):
        st.session_state.step = 2
        st.rerun()
    if scenarios:
        c2.download_button(
            "↓ Exporter Excel",
            data=export_excel(scenarios),
            file_name=f"EBIOS_RM_{st.session_state.nom.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    filtre = st.radio("Filtrer", ["Tous", "Critiques", "Validés", "En attente"], horizontal=True)
    shown = scenarios
    if filtre == "Critiques":
        shown = [s for s in scenarios if s["gravite"] == "Critique"]
    elif filtre == "Validés":
        shown = [s for s in scenarios if st.session_state.scen_status.get(s["id"]) == "validated"]
    elif filtre == "En attente":
        shown = [s for s in scenarios if st.session_state.scen_status.get(s["id"], "pending") == "pending"]

    for s in shown:
        status = st.session_state.scen_status.get(s["id"], "pending")
        status_label = {"pending": "🟡 En attente", "validated": "🟢 Validé", "rejected": "🔴 Rejeté"}[status]
        with st.expander(f"**{s['id']}** — {s['titre']}  ·  {s['vraisemblance']} / {s['gravite']}  ·  {s['score']}/12  ·  {status_label}"):
            c1, c2 = st.columns(2)
            c1.markdown(f"**Source de menace**\n\n{s['menace']}")
            c1.markdown(f"**Vulnérabilité**\n\n{s['vuln']}")
            c1.markdown(f"**Actif concerné**\n\n{s['actif']}")
            c2.markdown(f"**Impact opérationnel**\n\n{s['impact_op']}")
            c2.markdown(f"**Impact financier**\n\n{s['impact_fin']}")
            c2.markdown(f"**Impact réglementaire**\n\n{s['impact_reg']}")
            st.info("↳ **Recommandations**\n\n" + "\n\n".join(f"- {r.strip()}" for r in s["reco"].split("|")))

            b1, b2, b3 = st.columns(3)
            if b1.button("✓ Valider", key=f"val_{s['id']}"):
                st.session_state.scen_status[s["id"]] = "validated"
                st.rerun()
            if b2.button("✕ Rejeter", key=f"rej_{s['id']}"):
                st.session_state.scen_status[s["id"]] = "rejected"
                st.rerun()
            if b3.button("↺ Réinitialiser", key=f"rst_{s['id']}"):
                st.session_state.scen_status[s["id"]] = "pending"
                st.rerun()