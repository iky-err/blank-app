"""
Wrapper pour les appels à l'API Anthropic.

Point clé sécurité : ce module tourne uniquement côté serveur Streamlit.
La clé API n'est jamais envoyée au navigateur du consultant ni écrite dans le code :
elle est lue dans les secrets Streamlit, ou à défaut dans la variable d'environnement
ANTHROPIC_API_KEY (exécution locale, serveur interne).
"""

import json
import os
import re

import streamlit as st
from anthropic import Anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = 8000  # 15 chemins d'attaque en JSON dépassent parfois 4000 tokens
TIMEOUT_S = 180


def _secret(name: str) -> str:
    """Lit un secret Streamlit, puis la variable d'environnement du même nom."""
    try:
        value = st.secrets.get(name)
    except Exception:  # aucun fichier secrets.toml configuré
        value = None
    return (value or os.environ.get(name) or "").strip()


@st.cache_resource
def get_client() -> Anthropic:
    api_key = _secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Clé API Anthropic introuvable. Ajoutez ANTHROPIC_API_KEY dans les Secrets de l'app "
            "(Streamlit Community Cloud : Settings → Secrets) ou en variable d'environnement."
        )
    # max_retries : nouvelle tentative automatique en cas de surcharge ou d'erreur réseau passagère.
    return Anthropic(api_key=api_key, timeout=TIMEOUT_S, max_retries=2)


def _extract_json(text: str) -> str:
    """Isole le JSON de la réponse, même si le modèle ajoute des balises ``` ou une phrase autour."""
    text = re.sub(r"```[a-zA-Z]*\n?", "", text).replace("```", "").strip()
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return text
    start = min(starts)
    end = max(text.rfind("]"), text.rfind("}"))
    return text[start:end + 1] if end > start else text[start:]


def call_claude(system: str, user: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    client = get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "max_tokens":
        raise ValueError(
            "La réponse du modèle a été coupée (trop longue). Réduisez le nombre de chemins "
            "demandés ou relancez la génération."
        )
    return "".join(block.text for block in resp.content if block.type == "text")


def call_claude_json(system: str, user: str, max_tokens: int = DEFAULT_MAX_TOKENS):
    raw_text = call_claude(system, user, max_tokens=max_tokens)
    try:
        return json.loads(_extract_json(raw_text))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"La réponse du modèle n'est pas un JSON valide ({e}). "
            f"Début de la réponse reçue : {raw_text[:200]}..."
        ) from e