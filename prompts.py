"""Prompts et règles métier de l'outil EBIOS RM (Formind).

Flux : Atelier 1 (cadrage, valeurs métier, biens supports, événements redoutés, socle de
sécurité) -> Ateliers 2-3 (couples SR/OV, scénarios stratégiques et chemins d'attaque, validés
par le consultant) -> Atelier 4 (scénarios opérationnels), uniquement rattachés aux chemins
validés. Les mesures de sécurité proposées alimentent le traitement du risque (Atelier 5).

Les sources de risque (SR) et objectifs visés (OV) ci-dessous forment une typologie INDICATIVE,
inspirée du guide EBIOS RM de l'ANSSI et adaptée par Formind : le modèle s'en sert de base,
mais peut proposer une SR ou un OV plus précis si le contexte le justifie.
"""
import unicodedata

# ── Référentiels ────────────────────────────────────────────────────────────

# Sources de risque : libellé -> description (transmise au modèle).
SR_DESC = {
    "Cybercriminalité organisée":
        "Groupes structurés motivés par le gain : rançongiciel, fraude (dont fraude télécom), "
        "revente de données.",
    "Acteur étatique":
        "Services de renseignement ou groupes APT soutenus par un État ; moyens importants, "
        "attaques ciblées et persistantes.",
    "Groupe hacktiviste":
        "Groupes à motivation idéologique ou géopolitique : DDoS, défiguration, fuites de "
        "données revendiquées.",
    "Concurrent":
        "Concurrent agissant directement, via une officine d'intelligence économique ou via un initié.",
    "Collaborateur ou ex-collaborateur malveillant":
        "Personne disposant ou ayant disposé d'accès légitimes, qui agit délibérément contre "
        "l'organisation (inclut le profil « vengeur »).",
    "Prestataire ou partenaire malveillant":
        "Tiers lié par contrat qui agit délibérément contre l'organisation. À distinguer du "
        "prestataire compromis, qui est une partie prenante utilisée comme vecteur.",
    "Interne non malveillant (erreur, négligence)":
        "Collaborateur ou prestataire qui provoque un incident sans intention de nuire : erreur de "
        "configuration, mauvaise manipulation, non-respect d'une procédure. Hors périmètre EBIOS RM "
        "strict ; réservé aux scénarios d'erreur.",
}

# Objectifs visés : libellé -> description. L'OV exprime POURQUOI la source agit.
OV_DESC = {
    "Gain financier":
        "Fraude, extorsion par rançongiciel ou chantage, revente de données.",
    "Espionnage stratégique":
        "Collecte d'informations sur la stratégie, les infrastructures ou les projets de l'organisation.",
    "Surveillance des communications / abonnés":
        "Accès aux données de trafic, de localisation ou aux communications de personnes ciblées.",
    "Prépositionnement stratégique":
        "Implantation discrète et durable dans le SI en vue d'une action ultérieure.",
    "Entrave au fonctionnement":
        "Perturber, saboter ou rendre indisponibles des services internes ou clients.",
    "Atteinte à l'image / déstabilisation":
        "Provoquer une perte de confiance : divulgation publique de données, défiguration, "
        "campagne médiatique.",
    "Vengeance / pression":
        "Nuire à l'organisation pour se venger ou peser dans un litige.",
    "Non intentionnel":
        "Réservé à la source « Interne non malveillant (erreur, négligence) ».",
}

SOURCES_RISQUE = list(SR_DESC)
OBJECTIFS_VISES = list(OV_DESC)

# Couples SR / OV les plus plausibles. Un autre couple reste possible s'il est justifié.
COUPLES = {
    "Cybercriminalité organisée": ["Gain financier"],
    "Acteur étatique": [
        "Espionnage stratégique", "Surveillance des communications / abonnés",
        "Prépositionnement stratégique", "Entrave au fonctionnement",
    ],
    "Groupe hacktiviste": ["Atteinte à l'image / déstabilisation", "Entrave au fonctionnement"],
    "Concurrent": ["Espionnage stratégique"],
    "Collaborateur ou ex-collaborateur malveillant": ["Gain financier", "Vengeance / pression"],
    "Prestataire ou partenaire malveillant": ["Gain financier", "Vengeance / pression"],
    "Interne non malveillant (erreur, négligence)": ["Non intentionnel"],
}

# Variantes fréquentes (anciens libellés, pluriels, formulations du modèle) -> libellé officiel.
SR_ALIASES = {
    "Acteurs étatiques": "Acteur étatique",
    "État": "Acteur étatique",
    "Groupes hacktivistes": "Groupe hacktiviste",
    "Activiste idéologique": "Groupe hacktiviste",
    "Organisation criminelle": "Cybercriminalité organisée",
    "Collaborateur malveillant": "Collaborateur ou ex-collaborateur malveillant",
    "Vengeur": "Collaborateur ou ex-collaborateur malveillant",
    "Prestataire malveillant": "Prestataire ou partenaire malveillant",
    "Officine spécialisée": "Concurrent",
}
OV_ALIASES = {
    "Lucre": "Gain financier",
    "Gain financier / fraude / extorsion": "Gain financier",
    "Espionnage": "Espionnage stratégique",
    "Espionnage / collecte d'informations stratégiques": "Espionnage stratégique",
    "Influence / atteinte à l'image": "Atteinte à l'image / déstabilisation",
    "Sabotage": "Entrave au fonctionnement",
    "Sabotage ou atteinte opérationnelle": "Entrave au fonctionnement",
    "Perturbation ou indisponibilité de services": "Entrave au fonctionnement",
    "Vengeance": "Vengeance / pression",
}

NIVEAUX_VRAISEMBLANCE = ["Minime", "Significative", "Forte", "Quasi certaine"]
NIVEAUX_GRAVITE = ["Mineure", "Significative", "Grave", "Critique"]
MAX_SCORE = len(NIVEAUX_VRAISEMBLANCE) * len(NIVEAUX_GRAVITE)  # 16

# Catalogue de scénarios de référence proposés dans l'outil (le consultant peut en ajouter).
SCENARIOS_REFERENCE = {
    "REF-CONFIG": {
        "label": "Erreur de configuration lors d'un déploiement (Finance)",
        "desc": "Source : Interne non malveillant (administrateur, équipe projet) ou prestataire ; "
                "cause : erreur de configuration ou mise en production non maîtrisée sur un périmètre "
                "Finance ; événement redouté : exposition de données financières ou indisponibilité "
                "du service.",
    },
    "REF-USURP": {
        "label": "Usurpation d'identité à des fins de fraude financière",
        "desc": "Source : Cybercriminalité organisée, qui usurpe l'identité d'un dirigeant, d'un "
                "client, d'un fournisseur ou d'un collaborateur (phishing ciblé, compromission de "
                "messagerie, deepfake vocal) pour obtenir un virement ou détourner un paiement ; "
                "événement redouté : fraude et perte financière.",
    },
    "REF-SABOT": {
        "label": "Sabotage contractuel",
        "desc": "Source : Prestataire ou partenaire malveillant (prestataire, sous-traitant, "
                "partenaire) ou ex-collaborateur ; dégradation, blocage ou rétention d'un service, "
                "d'un accès ou de données pour nuire ou peser dans un litige ; événement redouté : "
                "rupture de continuité d'activité.",
    },
    "REF-RANSOM": {
        "label": "Rançongiciel sur le SI de production",
        "desc": "Source : Cybercriminalité organisée ; chiffrement des systèmes et extorsion ; "
                "événement redouté : arrêt prolongé de l'activité.",
    },
    "REF-SUPPLY": {
        "label": "Compromission via un prestataire (chaîne d'approvisionnement)",
        "desc": "Rebond depuis un prestataire ou une mise à jour logicielle compromise (le "
                "prestataire est la partie prenante, pas la source) vers le SI de l'organisation ; "
                "événement redouté : compromission de données ou du SI.",
    },
    "REF-EXFIL": {
        "label": "Exfiltration de données par un initié malveillant",
        "desc": "Source : Collaborateur ou ex-collaborateur malveillant qui extrait des données "
                "sensibles ; événement redouté : fuite de données et atteinte à l'image / sanction "
                "réglementaire.",
    },
}

SR_HINT = "\n".join(f"   - {k} : {v}" for k, v in SR_DESC.items())
OV_HINT = "\n".join(f"   - {k} : {v}" for k, v in OV_DESC.items())
COUPLES_HINT = "\n".join(f"   - {sr} -> {', '.join(ovs)}" for sr, ovs in COUPLES.items())

GRAVITE_DEF = """- Mineure : impacts négligeables ou absorbés sans difficulté.
- Significative : dégradation sensible mais sans conséquence durable.
- Grave : impacts importants (financiers, réglementaires, image), difficilement absorbés.
- Critique : menace la continuité d'activité ou la pérennité de l'organisation."""

VRAISEMBLANCE_DEF = """- Minime : très improbable au regard des capacités de la source de risque et des mesures en place.
- Significative : possible, mais nécessite des conditions particulières.
- Forte : probable, la source de risque a les moyens et l'opportunité.
- Quasi certaine : très probable, quasiment aucune barrière efficace."""

# ── Prompts ─────────────────────────────────────────────────────────────────

SYSTEM_SCAN = """Tu es un consultant senior en sécurité des systèmes d'information, expert de la méthode EBIOS Risk Manager (ANSSI). Tu interviens à la fin de l'Atelier 1 (cadrage et socle de sécurité) : à partir du cadrage fourni (périmètre, valeurs métier, biens supports, événements redoutés, référentiels applicables, parties prenantes de l'écosystème, état de la menace), tu évalues le socle de sécurité de l'organisation et tu prépares les Ateliers 2 et 3.

Utilise le vocabulaire EBIOS RM (valeurs métier, biens supports, événements redoutés, socle de sécurité, écarts, parties prenantes, sources de risque) plutôt que celui d'autres méthodes (actifs, menaces génériques…).

Réponds UNIQUEMENT par un objet JSON valide, sans texte autour ni balises markdown, avec exactement ces clés :
- "niveau_global" : niveau de maturité SSI estimé (indicateur complémentaire, hors méthode EBIOS RM), l'une de ces valeurs exactes : "Faible", "Moyen", "Satisfaisant", "Bon". Tiens compte des notes de maturité fournies ET du reste du contexte (incidents, effectifs, écarts).
- "resume" : 3 à 4 phrases de synthèse, factuelles, fondées uniquement sur le contexte fourni
- "forces" : liste de 3 à 5 points forts du socle de sécurité (chaînes courtes)
- "gaps" : liste de 3 à 6 écarts au socle de sécurité : mesures absentes ou insuffisantes au regard des référentiels applicables et des biens supports à protéger (chaînes courtes)
- "priorites" : liste de 3 à 5 domaines prioritaires (chaînes courtes)
- "recommandation" : 2 à 4 phrases. Indique en priorité les éléments du cadrage manquants ou imprécis qui fragiliseront les Ateliers 2 et 3 (valeurs métier, biens supports, événements redoutés et leur gravité, parties prenantes de l'écosystème, sources de risque plausibles) et ce que le consultant doit clarifier avec le client avant de continuer.

N'invente aucun fait absent du contexte. Si une information est marquée « ? » ou « Non précisée », traite-la comme inconnue."""

SYSTEM_PATHS = f"""Tu es un consultant senior en cybersécurité, certifié EBIOS Risk Manager (méthode ANSSI). Tu réalises l'Atelier 2 (couples source de risque / objectif visé) et l'Atelier 3 (scénarios stratégiques).

DÉFINITIONS
- Un scénario stratégique décrit comment une source de risque, pour atteindre son objectif visé, peut s'en prendre à l'organisation, directement ou via son écosystème.
- Un chemin d'attaque stratégique est la suite ordonnée d'événements de ce scénario : source de risque -> (partie prenante de l'écosystème utilisée comme vecteur, le cas échéant) -> valeur métier ciblée -> événement redouté.
- Chaque élément du tableau de sortie correspond à un chemin d'attaque.

RÈGLES IMPÉRATIVES
1. Sources de risque — typologie indicative. Utilise de préférence l'un de ces libellés, tel quel. Tu peux proposer une source plus précise si le contexte le justifie ; explique alors ce choix dans "justification".
{SR_HINT}
2. Objectifs visés — typologie indicative, même règle que pour les sources. L'objectif exprime POURQUOI la source agit (sa finalité), pas l'effet subi par l'organisation : l'exfiltration, l'indisponibilité ou la destruction relèvent du chemin et de l'événement redouté, pas de l'objectif.
{OV_HINT}
3. Couples source de risque / objectif visé les plus plausibles. Tout autre couple doit être justifié dans "justification" :
{COUPLES_HINT}
4. Partie prenante de l'écosystème : elle doit provenir du contexte (prestataires, sous-traitants, clients, partenaires, filiales). Privilégie les parties prenantes critiques au sens de l'Atelier 3 : forte dépendance de l'organisation à leur égard, accès étendu à son SI (pénétration), maturité cyber faible ou confiance limitée. Si le contexte n'en nomme aucune, utilise un rôle générique (ex. « prestataire d'infogérance »). Pour une attaque directe : « Aucune (attaque directe) ». Un prestataire compromis et utilisé comme vecteur est une partie prenante ; « Prestataire ou partenaire malveillant » n'est utilisé comme source que pour un acte délibéré.
5. Valeur métier et événement redouté : ils doivent correspondre aux valeurs métier et aux événements redoutés du cadrage (Atelier 1). Réutilise de préférence ceux fournis dans le contexte, avec leur gravité si elle est indiquée ; n'en crée de nouveaux que s'ils sont manifestement liés à l'activité décrite.
6. Gravité, échelle EBIOS RM (utilise EXACTEMENT : {", ".join(NIVEAUX_GRAVITE)}) :
{GRAVITE_DEF}
7. Réalisme : ne propose que des chemins plausibles pour le secteur, la taille, le socle de sécurité et les obligations de l'organisation, et cohérents avec les capacités de la source de risque.
8. Couverture du référentiel : chaque scénario de référence fourni DOIT donner lieu à au moins un chemin, avec ref_type égal à l'id exact du scénario de référence. Respecte la source, la cause et l'événement redouté décrits dans le référentiel, sans les dénaturer. Les autres chemins ont ref_type = "".
9. Diversité : pas de doublons ni de variantes cosmétiques ; varie les sources de risque, les objectifs et les parties prenantes. Deux chemins d'une même source doivent différer par l'objectif, la partie prenante ou la valeur métier ciblée.
10. Scénario non intentionnel (erreur de configuration, négligence) : source de risque « Interne non malveillant (erreur, négligence) » et objectif visé « Non intentionnel ».

FORMAT DE SORTIE
Réponds UNIQUEMENT par un tableau JSON valide, sans texte autour ni balises markdown. Chaque élément contient exactement ces clés :
- "id" : "CA-01", "CA-02", etc.
- "ref_type" : id du scénario de référence couvert, ou ""
- "source_risque", "objectif_vise", "partie_prenante", "valeur_metier", "evenement_redoute", "gravite"
- "chemin" : 3 à 5 étapes séparées par " -> " (de la source de risque à l'événement redouté)
- "justification" : 1 à 2 phrases expliquant pourquoi ce couple et ce chemin sont plausibles pour cette organisation"""

SYSTEM_EBIOS = f"""Tu es un consultant senior en cybersécurité, certifié EBIOS Risk Manager (méthode ANSSI). Tu réalises l'Atelier 4 : scénarios opérationnels, à partir de chemins d'attaque stratégiques DÉJÀ VALIDÉS par le consultant. Un scénario opérationnel décrit, au niveau technique, le mode opératoire par lequel la source de risque réalise le chemin d'attaque en exploitant les vulnérabilités des biens supports.

RÈGLES IMPÉRATIVES
1. Un scénario opérationnel par chemin d'attaque fourni, dans le même ordre. Chaque scénario porte le champ "chemin_id" égal à l'id exact du chemin. N'ajoute aucun scénario qui ne soit pas rattaché à un chemin fourni, et n'invente aucun chemin.
2. Reste fidèle au chemin : source de risque, objectif visé, partie prenante, valeur métier et événement redouté sont ceux du chemin. Si un scénario de référence est associé, respecte la source, la cause et l'événement redouté qu'il décrit.
3. Mode opératoire : exactement 4 éléments séparés par " | ", chacun commençant par le nom de la phase :
   « Connaître : ... » | « Rentrer : ... » | « Trouver : ... » | « Exploiter : ... »
   Adapte le niveau de sophistication aux capacités de la source de risque (un collaborateur isolé ou un groupe hacktiviste n'a pas les moyens d'un acteur étatique). Pour un scénario non intentionnel (objectif « Non intentionnel »), remplace les phases par « Contexte : ... » | « Déclencheur : ... » | « Propagation : ... » | « Conséquence : ... ».
4. Vraisemblance, échelle EBIOS RM (utilise EXACTEMENT : {", ".join(NIVEAUX_VRAISEMBLANCE)}), évaluée au regard du socle de sécurité et des mesures en place, de la maturité SSI et des capacités de la source de risque :
{VRAISEMBLANCE_DEF}
   La gravité est celle du chemin : ne la fournis pas.
5. "actif" : le bien support ciblé (composant sur lequel repose la valeur métier : système, logiciel, réseau, personne, local, prestataire), choisi de préférence parmi les biens supports du contexte. "vuln" : une vulnérabilité plausible de ce bien support, exploitée dans le mode opératoire.
6. "reco" : 3 à 4 mesures de sécurité concrètes et actionnables, séparées par " | ", qui répondent aux écarts au socle de sécurité et au mode opératoire décrit (pas de conseils génériques). Elles serviront au traitement du risque (Atelier 5).
7. "impact_op", "impact_fin", "impact_reg" : une ou deux phrases chacun, spécifiques à l'événement redouté ("impact_reg" couvre les impacts juridiques et réglementaires).

FORMAT DE SORTIE
Réponds UNIQUEMENT par un tableau JSON valide, sans texte autour ni balises markdown. Chaque élément contient exactement ces clés : "titre", "chemin_id", "mode_operatoire", "vuln", "actif", "impact_op", "impact_fin", "impact_reg", "vraisemblance", "reco"."""

# ── Utilitaires ─────────────────────────────────────────────────────────────


def _key(value) -> str:
    text = unicodedata.normalize("NFD", str(value)).encode("ascii", "ignore").decode()
    return text.lower().replace("-", " ").replace("_", " ").strip()


def normalize_choice(value, options, aliases=None):
    """Retourne le libellé canonique de `options` correspondant à `value`, sinon None."""
    k = _key(value)
    if not k:
        return None
    for opt in options:
        if _key(opt) == k:
            return opt
    for alias, target in (aliases or {}).items():
        if _key(alias) == k:
            return target
    for opt in options:
        ok = _key(opt)
        if k.startswith(ok) or ok.startswith(k):
            return opt
    return None


def score_scenario(vraisemblance: str, gravite: str) -> int:
    v = normalize_choice(vraisemblance, NIVEAUX_VRAISEMBLANCE)
    g = normalize_choice(gravite, NIVEAUX_GRAVITE)
    if v is None or g is None:
        raise ValueError(f"Niveau invalide : vraisemblance={vraisemblance!r}, gravité={gravite!r}")
    return (NIVEAUX_VRAISEMBLANCE.index(v) + 1) * (NIVEAUX_GRAVITE.index(g) + 1)


PATH_REQUIRED = [
    "source_risque", "objectif_vise", "partie_prenante",
    "valeur_metier", "evenement_redoute", "gravite", "chemin",
]

# Champs recopiés du chemin validé vers le scénario (garantit la cohérence avec la validation).
INHERITED_FIELDS = [
    "source_risque", "objectif_vise", "partie_prenante",
    "valeur_metier", "evenement_redoute", "gravite", "ref_type",
]

SCENARIO_REQUIRED = [
    "titre", "chemin_id", "mode_operatoire", "vuln", "actif",
    "impact_op", "impact_fin", "impact_reg", "vraisemblance", "reco",
]


def _clean(item: dict) -> dict:
    out = {}
    for k, v in item.items():
        if isinstance(v, list):
            v = " | ".join(str(x).strip() for x in v)
        out[k] = v.strip() if isinstance(v, str) else v
    return out


def validate_path(item, valid_refs):
    """Retourne le chemin normalisé, ou None s'il est inexploitable.

    Source et objectif hors typologie sont CONSERVÉS (typologie indicative) : l'interface les
    affiche en tête de liste et le consultant décide de les garder ou de les remplacer.
    """
    if not isinstance(item, dict):
        return None
    p = _clean(item)
    if not all(str(p.get(f, "")).strip() for f in PATH_REQUIRED):
        return None
    g = normalize_choice(p["gravite"], NIVEAUX_GRAVITE)
    if g is None:
        return None
    p["gravite"] = g
    p["source_risque"] = normalize_choice(p["source_risque"], SOURCES_RISQUE, SR_ALIASES) or p["source_risque"]
    p["objectif_vise"] = normalize_choice(p["objectif_vise"], OBJECTIFS_VISES, OV_ALIASES) or p["objectif_vise"]
    p["ref_type"] = p.get("ref_type") if p.get("ref_type") in valid_refs else ""
    p.setdefault("justification", "")
    return p


def validate_scenario(item, path_ids):
    """Retourne (scénario normalisé, None) ou (None, motif du rejet)."""
    if not isinstance(item, dict):
        return None, "format invalide"
    s = _clean(item)
    missing = [f for f in SCENARIO_REQUIRED if not str(s.get(f, "")).strip()]
    if missing:
        return None, f"champs manquants ({', '.join(missing)})"
    if s["chemin_id"] not in path_ids:
        return None, f"chemin d'attaque inconnu ({s['chemin_id']})"
    v = normalize_choice(s["vraisemblance"], NIVEAUX_VRAISEMBLANCE)
    if v is None:
        return None, f"vraisemblance invalide ({s['vraisemblance']})"
    s["vraisemblance"] = v
    return s, None


# ── Contrôles de qualité (avertissements, sans rejet) ───────────────────────

PHASES = ("Connaître", "Rentrer", "Trouver", "Exploiter")
PHASES_NON_INTENT = ("Contexte", "Déclencheur", "Propagation", "Conséquence")


def warnings_path(p) -> list[str]:
    """Signale ce qui mérite une relecture du consultant sur un chemin d'attaque."""
    w = []
    if p["source_risque"] not in SOURCES_RISQUE:
        w.append("Source de risque hors typologie : vérifiez la justification.")
    if p["objectif_vise"] not in OBJECTIFS_VISES:
        w.append("Objectif visé hors typologie : vérifiez la justification.")
    ok = COUPLES.get(p["source_risque"])
    if ok and p["objectif_vise"] in OBJECTIFS_VISES and p["objectif_vise"] not in ok:
        w.append(f"Couple inhabituel : {p['source_risque']} → {p['objectif_vise']}.")
    n = len([e for e in str(p["chemin"]).split("->") if e.strip()])
    if not 3 <= n <= 5:
        w.append(f"Chemin de {n} étape(s) au lieu de 3 à 5.")
    return w


def warnings_scenario(s) -> list[str]:
    """Signale ce qui mérite une relecture du consultant sur un scénario opérationnel."""
    w = []
    steps = [e.strip() for e in str(s["mode_operatoire"]).split("|") if e.strip()]
    attendu = PHASES_NON_INTENT if s.get("objectif_vise") == "Non intentionnel" else PHASES
    if len(steps) != 4 or not all(_key(st).startswith(_key(ph)) for st, ph in zip(steps, attendu)):
        w.append("Mode opératoire : les 4 phases attendues ne sont pas respectées.")
    n = len([r for r in str(s["reco"]).split("|") if r.strip()])
    if not 3 <= n <= 4:
        w.append(f"{n} mesure(s) de sécurité au lieu de 3 à 4.")
    return w


# ── Mise en forme pour les prompts ──────────────────────────────────────────


def format_refs(refs) -> str:
    return "\n".join(
        f"- id={r['id']} | {r['label']}" + (f" — {r['desc']}" if r.get("desc") else "")
        for r in refs
    )


def format_paths(paths) -> str:
    return "\n".join(
        f"- id={p['id']} | source de risque: {p['source_risque']} | objectif visé: {p['objectif_vise']}"
        f" | partie prenante: {p['partie_prenante']} | valeur métier: {p['valeur_metier']}"
        f" | événement redouté: {p['evenement_redoute']} | gravité: {p['gravite']}"
        f" | scénario de référence: {p.get('ref_type') or 'aucun'} | chemin: {p['chemin']}"
        for p in paths
    )