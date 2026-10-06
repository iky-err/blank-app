import io
import pandas as pd
import streamlit as st

from claude_client import call_claude_json
from prompts import (
    SYSTEM_SCAN, SYSTEM_PATHS, SYSTEM_EBIOS,
    SOURCES_RISQUE, OBJECTIFS_VISES, NIVEAUX_GRAVITE, MAX_SCORE,
    SCENARIOS_REFERENCE, INHERITED_FIELDS,
    format_refs, format_paths, score_scenario, validate_path, validate_scenario,
    warnings_path, warnings_scenario,
)

st.set_page_config(page_title="Formind — Outil EBIOS RM", page_icon="🛡️", layout="wide")

SECTEURS = [
    "Finance / Banque", "Santé", "Énergie / OIV", "Collectivité", "Industrie",
    "Tech / SaaS", "Transport", "Défense", "Assurance", "Retail", "Autre",
]
TAILLES = [
    "TPE (<50 sal.)", "PME (50-500 sal.)", "ETI (500-5000 sal.)",
    "GE (>5000 sal.)", "Administration", "OIV / OSE",
]
REGLEMENTS = ["RGPD", "NIS2","PCI-DSS", "ISO 27001", "DORA", "SOC 2"]
MAT_DIMS = [
    ("gov", "Gouvernance & Organisation"),
    ("risk", "Gestion des risques"),
    ("tech", "Protection technique"),
    ("inc", "Gestion des incidents"),
    ("conf", "Conformité & Audit"),
]
MAT_LABELS = {1: "Initial", 2: "Répété", 3: "Défini", 4: "Géré", 5: "Optimisé"}
NB_CHEMINS_OPTIONS = [5, 7, 10, 12, 15]
BATCH_SIZE = 4  # chemins traités par appel, pour éviter les réponses JSON tronquées
STATUS_LABELS = {"pending": "🟡 En attente", "validated": "🟢 Validé", "rejected": "🔴 Rejeté"}

defaults = {
    "step": 1,
    "nom": "", "secteur": SECTEURS[0], "secteur_autre": "",
    "taille": TAILLES[1], "perimetre": "", "biens_supports": "",
    "valeurs_metier": "", "evenements_redoutes": "", "sources_risque": [],
    "scenarios_ref": ["REF-CONFIG", "REF-USURP", "REF-SABOT"], "scenarios_ref_autre": "",
    "reglements": [], "reglement_autre": "",
    "incidents": "", "menaces": "",
    "equipe_it": "", "equipe_sec": "", "prestataires": "", "projets_recents": "",
    "notes": "",
    "maturite": {k: 2 for k, _ in MAT_DIMS},
    "nb_chemins": 7,
    "analysis": None,
    "paths": None,
    "path_status": {},
    "scenarios": None,
    "scen_status": {},
    "flash": "",
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)


# ── Helpers ────────────────────────────────────────────────────────────────

def get_refs() -> list[dict]:
    """Scénarios de référence du consultant : catalogue coché + lignes libres."""
    m = st.session_state
    refs = [{"id": rid, **SCENARIOS_REFERENCE[rid]} for rid in m["scenarios_ref"] if rid in SCENARIOS_REFERENCE]
    for i, line in enumerate(m["scenarios_ref_autre"].splitlines(), start=1):
        if line.strip():
            refs.append({"id": f"REF-C{i:02d}", "label": line.strip(), "desc": ""})
    return refs


def build_context() -> str:
    m = st.session_state
    mat_str = ", ".join(
        f"{label}: {m['maturite'][k]}/5 ({MAT_LABELS[m['maturite'][k]]})"
        for k, label in MAT_DIMS
    )
    regs = list(m["reglements"]) + ([m["reglement_autre"]] if m["reglement_autre"] else [])
    return f"""Organisation: {m['nom']}
Secteur: {m['secteur_autre'] if m['secteur'] == 'Autre' else m['secteur']} | Taille: {m['taille']}
Périmètre de l'étude (métier et technique): {m['perimetre'] or 'Non précisé'}
Valeurs métier: {m['valeurs_metier'] or 'Non précisées'}
Biens supports: {m['biens_supports'] or 'Non précisés'}
Événements redoutés identifiés: {m['evenements_redoutes'] or 'Non précisés'}
Sources de risque pressenties (consultant): {', '.join(m['sources_risque']) or 'Non précisées'}
Réglementation: {', '.join(regs) or 'Non précisée'}
Incidents passés: {m['incidents'] or 'Aucun signalé'}
État de la menace connu: {m['menaces'] or 'Non précisé'}
Équipe IT: {m['equipe_it'] or '?'} | Équipe sécurité: {m['equipe_sec'] or '?'}
Parties prenantes de l'écosystème: {m['prestataires'] or '?'}
Projets récents: {m['projets_recents'] or '?'}
Maturité SSI (indicateur complémentaire, hors EBIOS RM): {mat_str}
Notes consultant: {m['notes'] or 'Aucune'}"""


def validated_paths() -> list[dict]:
    m = st.session_state
    return [p for p in (m["paths"] or []) if m["path_status"].get(p["id"]) == "validated"]


def compute_coverage() -> list[dict]:
    """Pour chaque scénario de référence : chemin proposé ? validé ? scénario généré ?"""
    m = st.session_state
    paths = m["paths"] or []
    scenarios = [s for s in (m["scenarios"] or []) if m["scen_status"].get(s["id"]) != "rejected"]
    rows = []
    for r in get_refs():
        r_paths = [p for p in paths if p.get("ref_type") == r["id"]]
        r_valid = [p for p in r_paths if m["path_status"].get(p["id"]) == "validated"]
        r_scen = [s for s in scenarios if s.get("ref_type") == r["id"]]
        if r_scen:
            state = "✅ Couvert"
        elif r_valid:
            state = "⚠️ Chemin validé, scénario à générer"
        elif r_paths:
            state = "🟡 Chemin proposé, non validé"
        else:
            state = "❌ Aucun chemin d'attaque"
        rows.append({
            "Scénario de référence": r["label"],
            "Chemins": ", ".join(p["id"] for p in r_paths) or "—",
            "Scénarios": ", ".join(s["id"] for s in r_scen) or "—",
            "Couverture": state,
        })
    return rows


def generate_paths() -> None:
    m = st.session_state
    refs = get_refs()
    n = max(m["nb_chemins"], len(refs))
    raw = call_claude_json(
        SYSTEM_PATHS,
        f"Propose {n} chemins d'attaque stratégiques (au minimum un par scénario de référence).\n\n"
        f"CONTEXTE:\n{build_context()}\n\n"
        f"SCÉNARIOS DE RÉFÉRENCE À COUVRIR:\n{format_refs(refs) or 'Aucun'}",
    )
    if not isinstance(raw, list):
        raise ValueError("Format de réponse inattendu (tableau attendu).")

    valid_refs = {r["id"] for r in refs}
    paths = []
    for item in raw:
        p = validate_path(item, valid_refs)
        if p is None:
            continue
        p["id"] = f"CA-{len(paths) + 1:02d}"
        paths.append(p)
    if not paths:
        raise ValueError("Aucun chemin d'attaque exploitable n'a pu être extrait. Réessayez.")
    if len(paths) < len(raw):
        m["flash"] = f"{len(raw) - len(paths)} chemin(s) incomplet(s) ignoré(s)."

    m["paths"] = paths
    m["path_status"] = {p["id"]: "pending" for p in paths}
    # Nouveaux chemins = nouveaux CA-01, CA-02… : les anciens scénarios ne leur correspondent plus.
    m["scenarios"] = None
    m["scen_status"] = {}


def inherit(s: dict, path: dict) -> dict:
    """Recopie les champs du chemin validé dans le scénario et recalcule le score."""
    for f in INHERITED_FIELDS:
        s[f] = path.get(f, "")
    s["score"] = score_scenario(s["vraisemblance"], s["gravite"])
    return s


def generate_scenarios_for(paths_todo: list[dict], start: int) -> list[dict]:
    refs = get_refs()
    by_id = {p["id"]: p for p in paths_todo}
    out, n = [], start
    for i in range(0, len(paths_todo), BATCH_SIZE):
        chunk = paths_todo[i:i + BATCH_SIZE]
        chunk_ids = {p["id"] for p in chunk}
        raw = call_claude_json(
            SYSTEM_EBIOS,
            "Génère un scénario opérationnel pour chacun des chemins d'attaque validés ci-dessous.\n\n"
            f"CONTEXTE:\n{build_context()}\n\n"
            f"SCÉNARIOS DE RÉFÉRENCE:\n{format_refs(refs) or 'Aucun'}\n\n"
            f"CHEMINS D'ATTAQUE VALIDÉS:\n{format_paths(chunk)}",
        )
        if not isinstance(raw, list):
            raise ValueError("Format de réponse inattendu (tableau attendu).")
        seen = set()
        for item in raw:
            s, err = validate_scenario(item, chunk_ids)
            if err or s["chemin_id"] in seen:
                continue
            seen.add(s["chemin_id"])
            s = inherit(s, by_id[s["chemin_id"]])
            s["id"] = f"SO-{n:03d}"
            n += 1
            out.append(s)
    return out


def build_scenarios() -> None:
    """Conserve les scénarios des chemins toujours validés, génère ceux qui manquent."""
    m = st.session_state
    valid = validated_paths()
    by_id = {p["id"]: p for p in valid}

    kept = [inherit(s, by_id[s["chemin_id"]]) for s in (m["scenarios"] or []) if s["chemin_id"] in by_id]
    have = {s["chemin_id"] for s in kept}
    todo = [p for p in valid if p["id"] not in have]

    start = max((int(s["id"].split("-")[1]) for s in kept), default=0) + 1
    new = generate_scenarios_for(todo, start) if todo else []

    scenarios = kept + new
    if not scenarios:
        raise ValueError("Aucun scénario exploitable n'a pu être extrait. Réessayez la génération.")

    missing = len(todo) - len(new)
    if missing:
        m["flash"] = f"{missing} chemin(s) validé(s) sans scénario exploitable : relancez la génération des scénarios manquants."

    m["scenarios"] = scenarios
    m["scen_status"] = {s["id"]: m["scen_status"].get(s["id"], "pending") for s in scenarios}


def export_excel(scenarios: list[dict]) -> bytes:
    m = st.session_state
    refs = {r["id"]: r["label"] for r in get_refs()}
    br = lambda series: series.astype(str).str.replace(" | ", "\n", regex=False).str.replace("|", "\n", regex=False)

    df = pd.DataFrame(scenarios)
    df["statut"] = df["id"].map(lambda i: STATUS_LABELS[m["scen_status"].get(i, "pending")][2:].strip())
    df["ref_type"] = df["ref_type"].map(lambda r: refs.get(r, ""))
    for c in ("mode_operatoire", "reco"):
        df[c] = br(df[c])
    cols = {
        "id": "ID", "titre": "Titre", "chemin_id": "Chemin d'attaque", "ref_type": "Scénario de référence",
        "source_risque": "Source de risque", "objectif_vise": "Objectif visé",
        "partie_prenante": "Partie prenante", "valeur_metier": "Valeur métier",
        "evenement_redoute": "Événement redouté", "mode_operatoire": "Mode opératoire",
        "actif": "Bien support ciblé", "vuln": "Vulnérabilité exploitée", "impact_op": "Impact opérationnel",
        "impact_fin": "Impact financier", "impact_reg": "Impact juridique / réglementaire",
        "vraisemblance": "Vraisemblance", "gravite": "Gravité", "score": f"Niveau de risque G×V (/{MAX_SCORE})",
        "reco": "Mesures de sécurité proposées", "statut": "Statut",
    }
    df = df[[c for c in cols if c in df.columns]].rename(columns=cols)

    pdf = pd.DataFrame(m["paths"] or [])
    if not pdf.empty:
        pdf["statut"] = pdf["id"].map(lambda i: STATUS_LABELS[m["path_status"].get(i, "pending")][2:].strip())
        pdf["ref_type"] = pdf["ref_type"].map(lambda r: refs.get(r, ""))
        pcols = {
            "id": "ID", "source_risque": "Source de risque", "objectif_vise": "Objectif visé",
            "partie_prenante": "Partie prenante", "valeur_metier": "Valeur métier",
            "evenement_redoute": "Événement redouté", "gravite": "Gravité", "chemin": "Chemin d'attaque",
            "ref_type": "Scénario de référence", "justification": "Justification", "statut": "Statut",
        }
        pdf = pdf[[c for c in pcols if c in pdf.columns]].rename(columns=pcols)

    # Empêche l'injection de formules : une cellule commençant par = + - @ serait interprétée par Excel.
    def _safe(v):
        if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
            return "'" + v
        return v

    _map = "map" if hasattr(pd.DataFrame, "map") else "applymap"  # pandas < 2.1 : applymap
    df = getattr(df, _map)(_safe)
    if not pdf.empty:
        pdf = getattr(pdf, _map)(_safe)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Scénarios opérationnels")
        if not pdf.empty:
            pdf.to_excel(writer, index=False, sheet_name="Chemins d'attaque")
        cov = compute_coverage()
        if cov:
            pd.DataFrame(cov).to_excel(writer, index=False, sheet_name="Couverture référentiel")
    return buf.getvalue()


# ── En-tête & progression ──────────────────────────────────────────────────

st.title("🛡️ Formind — Outil consultant EBIOS RM")
cols = st.columns(4)
labels = [
    "1. Cadrage et socle", "2. Socle de sécurité",
    "3. Scénarios stratégiques", "4. Scénarios opérationnels",
]
for i, col in enumerate(cols, start=1):
    with col:
        marker = "✅" if st.session_state.step > i else ("▶️" if st.session_state.step == i else "⬜")
        st.markdown(f"**{marker} {labels[i - 1]}**")
st.divider()

if st.session_state.flash:
    st.warning(st.session_state.flash, icon="⚠️")
    st.session_state.flash = ""

# ── Étape 1 : atelier 1, cadrage ────────────────────────────────────────────────────

if st.session_state.step == 1:
    st.subheader("📋 Atelier 1 — Cadrage et socle de sécurité")

    c1, c2 = st.columns(2)
    st.session_state.nom = c1.text_input("Nom de l'organisation *", st.session_state.nom)
    st.session_state.taille = c2.selectbox("Taille", TAILLES, index=TAILLES.index(st.session_state.taille))
    st.session_state.secteur = st.selectbox("Secteur d'activité", SECTEURS, index=SECTEURS.index(st.session_state.secteur))
    if st.session_state.secteur == "Autre":
        st.session_state.secteur_autre = st.text_input("Précisez le secteur *", st.session_state.secteur_autre)
    st.session_state.perimetre = st.text_area(
        "Périmètre de l'étude (métier et technique) *",
        st.session_state.perimetre,
        placeholder="ex: activité de paiement et SI Finance, sites de Casablanca et Rabat…",
    )
    st.session_state.valeurs_metier = st.text_area(
        "Valeurs métier",
        st.session_state.valeurs_metier,
        placeholder="ex: Exécution des paiements, gestion des comptes clients, reporting financier réglementaire…",
        help="Processus et informations essentiels à l'organisation.",
    )
    st.session_state.biens_supports = st.text_area(
        "Biens supports",
        st.session_state.biens_supports,
        placeholder="ex: ERP Finance → exécution des paiements ; base de données clients → gestion des comptes ; équipe trésorerie…",
        help="Composants sur lesquels reposent les valeurs métier : systèmes, logiciels, réseaux, personnes, "
             "locaux, prestataires. Indiquez si possible la valeur métier soutenue (bien support → valeur métier).",
    )
    st.session_state.evenements_redoutes = st.text_area(
        "Événements redoutés (avec gravité si connue)",
        st.session_state.evenements_redoutes,
        placeholder="ex: Détournement de virements — Critique ; indisponibilité du SI Finance > 24 h — Grave",
    )

    st.markdown("**Cadrage EBIOS RM**")
    st.session_state.sources_risque = st.multiselect(
        "Sources de risque pressenties (facultatif)",
        SOURCES_RISQUE,
        default=st.session_state.sources_risque,
        help="Typologie indicative inspirée du guide ANSSI. Laissez vide pour laisser le modèle proposer les sources plausibles.",
    )
    st.session_state.scenarios_ref = st.multiselect(
        "Scénarios de référence à couvrir",
        list(SCENARIOS_REFERENCE),
        default=st.session_state.scenarios_ref,
        format_func=lambda rid: SCENARIOS_REFERENCE[rid]["label"],
        help="Chaque scénario coché donnera lieu à au moins un chemin d'attaque proposé, puis à un scénario.",
    )
    st.session_state.scenarios_ref_autre = st.text_area(
        "Autres scénarios de référence (un par ligne)",
        st.session_state.scenarios_ref_autre,
        height=80,
    )

    st.markdown("**Socle de sécurité**")
    st.session_state.reglements = st.multiselect(
        "Référentiels et réglementations applicables",
        REGLEMENTS,
        default=st.session_state.reglements,
    )
    st.session_state.reglement_autre = st.text_input("Autres obligations spécifiques", st.session_state.reglement_autre)

    c1, c2 = st.columns(2)
    st.session_state.equipe_it = c1.text_input("Effectif équipe IT", st.session_state.equipe_it)
    st.session_state.equipe_sec = c2.text_input("Effectif équipe sécurité", st.session_state.equipe_sec)
    st.session_state.prestataires = st.text_input(
        "Parties prenantes de l'écosystème",
        st.session_state.prestataires,
        placeholder="ex: prestataire d'infogérance, éditeur de l'ERP, partenaires bancaires, filiales, clients…",
    )
    st.session_state.projets_recents = st.text_input("Projets SI en cours ou récents", st.session_state.projets_recents)

    st.session_state.incidents = st.text_area("Incidents de sécurité passés", st.session_state.incidents)
    st.session_state.menaces = st.text_area("État de la menace connu (veille, alertes sectorielles)", st.session_state.menaces)

    st.markdown("**Maturité SSI** (1 = Initial → 5 = Optimisé) — indicateur complémentaire Formind, hors méthode EBIOS RM")
    for k, label in MAT_DIMS:
        st.session_state.maturite[k] = st.slider(label, 1, 5, st.session_state.maturite[k])

    st.session_state.nb_chemins = st.selectbox(
        "Nombre de chemins d'attaque à proposer",
        NB_CHEMINS_OPTIONS,
        index=NB_CHEMINS_OPTIONS.index(st.session_state.nb_chemins),
        help="Un scénario opérationnel sera généré par chemin que vous validerez.",
    )
    st.session_state.notes = st.text_input("Notes du consultant", st.session_state.notes)

    if st.button("✦ Analyser le socle de sécurité et passer à l'étape 2 →", type="primary", width="stretch"):
        if not st.session_state.nom.strip() or not st.session_state.perimetre.strip():
            st.error("⚠ Veuillez renseigner au minimum le nom et le périmètre.")
        else:
            with st.spinner("Analyse du contexte en cours…"):
                try:
                    analysis = call_claude_json(
                        SYSTEM_SCAN, f"Analyse ce contexte:\n\n{build_context()}"
                    )
                    if not isinstance(analysis, dict):
                        raise ValueError("Format de réponse inattendu (objet attendu). Réessayez.")
                    st.session_state.analysis = analysis
                    st.session_state.step = 2
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

# ── Étape 2 : socle de sécurité ────────────────────────────────────────

elif st.session_state.step == 2:
    a = st.session_state.analysis or {}
    st.subheader(f"🔍 Atelier 1 — Socle de sécurité — {st.session_state.nom}")

    niveau = a.get("niveau_global", "Non évalué")
    niveau_icon = {"Faible": "🔴", "Moyen": "🟡", "Satisfaisant": "🟢", "Bon": "✅"}.get(niveau, "📊")
    st.info(f"{niveau_icon} **Niveau de maturité SSI estimé : {niveau}**\n\n{a.get('resume', '')}")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**✅ Points forts du socle**")
        for f in a.get("forces", []):
            st.markdown(f"- {f}")
    with c2:
        st.markdown("**⚠️ Écarts au socle de sécurité**")
        for g in a.get("gaps", []):
            st.markdown(f"- {g}")
    with c3:
        st.markdown("**🎯 Domaines prioritaires**")
        for p in a.get("priorites", []):
            st.markdown(f"- {p}")

    if a.get("recommandation"):
        st.warning(f"💡 **À clarifier avec le client avant les ateliers 2 et 3**\n\n{a['recommandation']}")

    c1, c2 = st.columns([1, 4])
    if c1.button("← Retour"):
        st.session_state.step = 1
        st.rerun()
    if c2.button("🧭 Proposer les scénarios stratégiques →", type="primary", width="stretch"):
        with st.spinner("Construction des couples SR/OV et des chemins d'attaque…"):
            try:
                generate_paths()
                st.session_state.step = 3
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ── Étape 3 : chemins d'attaque (Ateliers 2-3) ─────────────────────────────

elif st.session_state.step == 3:
    paths = st.session_state.paths or []
    pstatus = st.session_state.path_status
    refs = get_refs()
    ref_ids = [""] + [r["id"] for r in refs]
    ref_lbl = {"": "— Aucun (hors référentiel)", **{r["id"]: r["label"] for r in refs}}

    st.subheader(f"🧭 Ateliers 2 et 3 — Scénarios stratégiques — {st.session_state.nom}")
    st.caption(
        "Chaque scénario stratégique associe un couple source de risque / objectif visé (atelier 2) "
        "à un chemin d'attaque passant, le cas échéant, par une partie prenante de l'écosystème (atelier 3). "
        "Ajustez puis validez ceux qui serviront de base aux scénarios opérationnels : "
        "seuls les chemins validés alimentent l'atelier 4."
    )

    n_val = sum(1 for p in paths if pstatus.get(p["id"]) == "validated")
    n_pend = sum(1 for p in paths if pstatus.get(p["id"], "pending") == "pending")
    m1, m2, m3 = st.columns(3)
    m1.metric("Chemins proposés", len(paths))
    m2.metric("Validés", n_val)
    m3.metric("En attente", n_pend)

    coverage = compute_coverage()
    if coverage:
        st.markdown("**Couverture des scénarios de référence**")
        st.dataframe(coverage, hide_index=True, width="stretch")

    for p in paths:
        pid = p["id"]
        status = pstatus.get(pid, "pending")
        with st.expander(
            f"**{pid}** — {p['source_risque']} → {p['objectif_vise']}  ·  {p['evenement_redoute']}  ·  "
            f"{p['gravite']}  ·  {STATUS_LABELS[status]}"
        ):
            c1, c2 = st.columns(2)
            sr_opts = SOURCES_RISQUE if p["source_risque"] in SOURCES_RISQUE else [p["source_risque"]] + SOURCES_RISQUE
            ov_opts = OBJECTIFS_VISES if p["objectif_vise"] in OBJECTIFS_VISES else [p["objectif_vise"]] + OBJECTIFS_VISES
            p["source_risque"] = c1.selectbox("Source de risque", sr_opts, index=sr_opts.index(p["source_risque"]), key=f"sr_{pid}")
            p["objectif_vise"] = c2.selectbox("Objectif visé", ov_opts, index=ov_opts.index(p["objectif_vise"]), key=f"ov_{pid}")
            p["partie_prenante"] = c1.text_input("Partie prenante de l'écosystème", p["partie_prenante"], key=f"pp_{pid}")
            p["valeur_metier"] = c2.text_input("Valeur métier", p["valeur_metier"], key=f"vm_{pid}")
            p["evenement_redoute"] = c1.text_input("Événement redouté", p["evenement_redoute"], key=f"er_{pid}")
            p["gravite"] = c2.selectbox("Gravité", NIVEAUX_GRAVITE, index=NIVEAUX_GRAVITE.index(p["gravite"]), key=f"gr_{pid}")
            p["chemin"] = st.text_area("Chemin d'attaque", p["chemin"], key=f"ch_{pid}")
            cur_ref = p.get("ref_type", "") if p.get("ref_type", "") in ref_ids else ""
            p["ref_type"] = st.selectbox(
                "Scénario de référence associé", ref_ids, index=ref_ids.index(cur_ref),
                format_func=lambda x: ref_lbl[x], key=f"rf_{pid}",
            )
            if p.get("justification"):
                st.caption(f"Justification : {p['justification']}")
            for msg in warnings_path(p):
                st.warning(msg, icon="⚠️")

            b1, b2, b3 = st.columns(3)
            if b1.button("✓ Valider", key=f"pval_{pid}"):
                pstatus[pid] = "validated"
                st.rerun()
            if b2.button("✕ Rejeter", key=f"prej_{pid}"):
                pstatus[pid] = "rejected"
                st.rerun()
            if b3.button("↺ Réinitialiser", key=f"prst_{pid}"):
                pstatus[pid] = "pending"
                st.rerun()

    with st.expander("➕ Ajouter un chemin d'attaque manuellement"):
        with st.form("add_path", clear_on_submit=True):
            c1, c2 = st.columns(2)
            f_sr = c1.selectbox("Source de risque", SOURCES_RISQUE)
            f_ov = c2.selectbox("Objectif visé", OBJECTIFS_VISES)
            f_pp = c1.text_input("Partie prenante de l'écosystème", placeholder="ou « Aucune (attaque directe) »")
            f_vm = c2.text_input("Valeur métier")
            f_er = c1.text_input("Événement redouté")
            f_gr = c2.selectbox("Gravité", NIVEAUX_GRAVITE, index=len(NIVEAUX_GRAVITE) - 1)
            f_ch = st.text_area("Chemin d'attaque", placeholder="Source de risque -> partie prenante -> valeur métier -> événement redouté")
            f_rf = st.selectbox("Scénario de référence associé", ref_ids, format_func=lambda x: ref_lbl[x])
            submitted = st.form_submit_button("Ajouter et valider ce chemin")
        if submitted:
            new = validate_path({
                "source_risque": f_sr, "objectif_vise": f_ov, "partie_prenante": f_pp,
                "valeur_metier": f_vm, "evenement_redoute": f_er, "gravite": f_gr,
                "chemin": f_ch, "ref_type": f_rf, "justification": "Ajouté par le consultant.",
            }, {r["id"] for r in refs})
            if new is None:
                st.error("⚠ Tous les champs sont obligatoires.")
            else:
                new["id"] = f"CA-{len(paths) + 1:02d}"
                paths.append(new)
                pstatus[new["id"]] = "validated"
                st.rerun()

    uncovered = [
        r["Scénario de référence"] for r in coverage
        if r["Couverture"].startswith(("🟡", "❌"))
    ]
    if uncovered:
        st.warning(
            "Scénarios de référence sans chemin validé : " + " ; ".join(uncovered)
            + ". Validez un chemin associé ou ajoutez-en un manuellement pour qu'ils soient couverts."
        )

    valid = validated_paths()
    c1, c2 = st.columns([1, 4])
    if c1.button("← Retour"):
        st.session_state.step = 2
        st.rerun()
    if c2.button(
        f"⚡ Générer les scénarios opérationnels ({len(valid)} chemin(s) validé(s)) →",
        type="primary", width="stretch", disabled=not valid,
    ):
        with st.spinner("Génération des scénarios opérationnels EBIOS RM…"):
            try:
                build_scenarios()
                st.session_state.step = 4
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ── Étape 4 : scénarios opérationnels (Atelier 4) ──────────────────────────

elif st.session_state.step == 4:
    scenarios = st.session_state.scenarios or []
    by_path = {p["id"]: p for p in (st.session_state.paths or [])}
    ref_lbl = {r["id"]: r["label"] for r in get_refs()}

    st.subheader(f"🛡 Atelier 4 — Scénarios opérationnels — {st.session_state.nom}")
    st.caption(
        f"{len(scenarios)} scénarios opérationnels, chacun rattaché à un chemin d'attaque validé · "
        "Validez, modifiez ou rejetez chaque scénario. "
        "Le niveau de risque est le produit gravité × vraisemblance."
    )

    # Les indicateurs ne comptent pas les scénarios rejetés.
    actifs_stats = [s for s in scenarios if st.session_state.scen_status.get(s["id"]) != "rejected"]
    crit = sum(1 for s in actifs_stats if s["gravite"] == "Critique")
    val = sum(1 for v in st.session_state.scen_status.values() if v == "validated")
    avg = round(sum(s["score"] for s in actifs_stats) / len(actifs_stats), 1) if actifs_stats else 0
    coverage = compute_coverage()
    covered = sum(1 for r in coverage if r["Couverture"].startswith("✅"))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Scénarios retenus", len(actifs_stats))
    m2.metric("Gravité critique", crit)
    m3.metric("Validés", val)
    m4.metric(f"Niveau de risque moyen (/{MAX_SCORE})", avg)
    m5.metric("Référentiel couvert", f"{covered}/{len(coverage)}" if coverage else "—")

    if coverage:
        st.markdown("**Couverture des scénarios de référence**")
        st.dataframe(coverage, hide_index=True, width="stretch")

    have = {s["chemin_id"] for s in scenarios}
    todo = [p for p in validated_paths() if p["id"] not in have]
    if todo:
        st.warning(
            f"{len(todo)} chemin(s) validé(s) n'ont pas de scénario : "
            + ", ".join(p["id"] for p in todo)
        )
        if st.button("↻ Générer les scénarios manquants"):
            with st.spinner("Génération des scénarios manquants…"):
                try:
                    build_scenarios()
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    c1, c2 = st.columns([1, 4])
    if c1.button("← Retour"):
        st.session_state.step = 3
        st.rerun()
    if scenarios:
        c2.download_button(
            "↓ Exporter Excel",
            data=export_excel(scenarios),
            file_name=f"EBIOS_RM_{st.session_state.nom.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    filtre = st.radio("Filtrer", ["Tous", "Gravité critique", "Validés", "En attente"], horizontal=True)
    shown = scenarios
    if filtre == "Gravité critique":
        shown = [s for s in scenarios if s["gravite"] == "Critique"]
    elif filtre == "Validés":
        shown = [s for s in scenarios if st.session_state.scen_status.get(s["id"]) == "validated"]
    elif filtre == "En attente":
        shown = [s for s in scenarios if st.session_state.scen_status.get(s["id"], "pending") == "pending"]

    for s in shown:
        status = st.session_state.scen_status.get(s["id"], "pending")
        with st.expander(
            f"**{s['id']}** — {s['titre']}  ·  {s['chemin_id']}  ·  V : {s['vraisemblance']} / G : {s['gravite']}  ·  "
            f"risque {s['score']}/{MAX_SCORE}  ·  {STATUS_LABELS[status]}"
        ):
            path = by_path.get(s["chemin_id"], {})
            c1, c2 = st.columns(2)
            c1.markdown(f"**Source de risque**\n\n{s['source_risque']} → *{s['objectif_vise']}*")
            c1.markdown(f"**Chemin d'attaque {s['chemin_id']}**\n\n{path.get('chemin', '—')}")
            c1.markdown(f"**Partie prenante de l'écosystème**\n\n{s['partie_prenante']}")
            c1.markdown(f"**Bien support ciblé**\n\n{s['actif']}")
            c1.markdown(f"**Vulnérabilité exploitée**\n\n{s['vuln']}")
            c2.markdown(f"**Valeur métier → événement redouté**\n\n{s['valeur_metier']} → {s['evenement_redoute']}")
            c2.markdown(f"**Impact opérationnel**\n\n{s['impact_op']}")
            c2.markdown(f"**Impact financier**\n\n{s['impact_fin']}")
            c2.markdown(f"**Impact juridique / réglementaire**\n\n{s['impact_reg']}")

            st.markdown("**Mode opératoire**\n\n" + "\n".join(
                f"{i}. {step.strip()}" for i, step in enumerate(s["mode_operatoire"].split("|"), start=1)
            ))
            if s.get("ref_type") in ref_lbl:
                st.caption(f"Scénario de référence : {ref_lbl[s['ref_type']]}")
            st.info("↳ **Mesures de sécurité proposées** (à reprendre dans le traitement du risque, atelier 5)\n\n"
                    + "\n\n".join(f"- {r.strip()}" for r in s["reco"].split("|")))
            for msg in warnings_scenario(s):
                st.warning(msg, icon="⚠️")

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