"""
Wrapper pour les appels à l'API Anthropic.

Point clé sécurité : ce module tourne uniquement côté serveur Streamlit.
La clé API n'est jamais envoyée au navigateur du consultant.
"""

import json
import re
import streamlit as st
from anthropic import Anthropic

MODEL = "claude-sonnet-4-6"


@st.cache_resource
def get_client() -> Anthropic:
    api_key = st.secrets.get("ANTHROPIC_API_KEY") or None
    if not api_key:
        raise RuntimeError(
            "Clé API Anthropic introuvable. Ajoute-la dans les Secrets de l'app "
            "sur Streamlit Community Cloud (Settings → Secrets)."
        )
    return Anthropic(api_key=api_key)


def _strip_code_fences(text: str) -> str:
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)
    return text.replace("```", "").strip()


def call_claude(system: str, user: str, max_tokens: int = 4000) -> str:
    client = get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    return _strip_code_fences(text)


def call_claude_json(system: str, user: str, max_tokens: int = 4000):
    raw_text = call_claude(system, user, max_tokens=max_tokens)
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"La réponse du modèle n'est pas un JSON valide ({e}). "
            f"Début de la réponse reçue : {raw_text[:200]}..."
        ) from e