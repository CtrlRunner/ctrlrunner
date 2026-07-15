"""
The UI Mode frontend.

The page is a prebuilt React app (frontend/src/ui/ in the repo root,
built with Vite into src/ctrlrunner/ui/_static/ui/ui.html as ONE self-contained
file with all JS/CSS inlined and committed to git, same setup as the
static HTML report). This module only injects the per-launch session
token into that page.
"""

from importlib import resources

_TOKEN_PLACEHOLDER = "__CTRLRUNNER_SESSION_TOKEN__"


def render_ui_html(token: str) -> str:
    """Injects the per-launch session token (see localsec.py) into the
    served page. The token is embedded here, server-side, rather than
    fetched over HTTP -- a page that never received it (a cross-site
    attacker, or a different local process) therefore can't read it and
    can't forge the X-Ctrlrunner-Token header the state-changing POST
    endpoints require."""
    page = resources.files("ctrlrunner.ui").joinpath("_static/ui/ui.html").read_text(encoding="utf-8")
    if _TOKEN_PLACEHOLDER not in page:
        raise RuntimeError(
            "Prebuilt UI page is missing its session-token placeholder -- "
            "rebuild the frontend (cd frontend && npm run build)"
        )
    return page.replace(_TOKEN_PLACEHOLDER, token)
