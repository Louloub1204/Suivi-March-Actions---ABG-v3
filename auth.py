"""Simple password gate.

Reads the expected password from Streamlit Secrets:

    [auth]
    password = "your-shared-password"

If the section is missing, the gate is disabled (useful for local dev).
"""
from __future__ import annotations

import hmac

import streamlit as st


def _expected_password() -> str | None:
    try:
        return st.secrets["auth"]["password"]
    except Exception:
        return None


def require_login() -> None:
    """Block app rendering until the correct password is entered.

    On success, sets `st.session_state['_authed'] = True` so subsequent
    reruns skip the prompt.
    """
    expected = _expected_password()
    if not expected:
        # No password configured → gate disabled (e.g. local dev).
        return

    if st.session_state.get("_authed"):
        return

    st.markdown("## 🔐 Accès protégé")
    st.caption("Cette application est réservée aux utilisateurs autorisés.")

    pwd = st.text_input(
        "Mot de passe",
        type="password",
        key="_pwd_input",
        autocomplete="current-password",
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        submitted = st.button("Se connecter", type="primary")

    if submitted:
        if hmac.compare_digest(pwd, expected):
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")

    st.stop()
