"""
Shared localhost-server hardening for pyrunner's two stdlib http.server
based servers: UI Mode's JSON/SSE API (ui_server.py) and the static
report server (show_report.py). Kept in one place so those two servers
can't drift apart on their defenses again -- they historically had
inconsistent, and in one case bypassable, origin handling.

"Bound to 127.0.0.1" is not by itself a security boundary against a
browser: any web page the user has open can fetch()/navigate to
http://127.0.0.1:<port>, and a DNS-rebinding attack can make an
attacker-controlled hostname resolve to 127.0.0.1 so the browser's own
same-origin machinery treats the request as same-site. The layered
defenses here address that:

  * host_allowed()  -- reject any request whose Host header isn't one of
    this server's own loopback names. This is the DNS-rebinding defense:
    a rebound request necessarily carries the attacker's own hostname in
    Host (that's what the victim's browser connected to), which is never
    in the allowlist.
  * origin_allowed() -- for state-changing requests, reject when an
    Origin/Referer is present but doesn't name this server. Compared
    against the KNOWN bound port, never echoed back from the request's
    own Host header (echoing Host was the previous bypass: an attacker
    sets Origin and Host to the same value and they trivially match).
  * new_session_token()/token_matches() -- a per-launch secret embedded
    in the served page and required on state-changing endpoints, so a
    different local user/process on a shared machine (which can send a
    correct Host and omit Origin) still can't drive the server.
"""

from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlsplit

# Header the frontend attaches the per-launch session token to on every
# state-changing POST. A custom header can't be set by a cross-site
# <form> submission and can't be forged by a page that never saw the
# token, so requiring it turns the token into a real CSRF/local-process
# gate. Note EventSource (the SSE stream) can't set custom headers, which
# is exactly why only state-changing POSTs -- never GETs -- require it.
TOKEN_HEADER = "X-Pyrunner-Token"


def allowed_hosts(port: int) -> frozenset[str]:
    """The exact Host header values this loopback server answers to.
    Anything else -- including a rebound attacker hostname that happens
    to resolve to 127.0.0.1 -- is rejected by host_allowed()."""
    return frozenset(
        {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            f"[::1]:{port}",
        }
    )


def host_allowed(host_header: str | None, port: int) -> bool:
    """True only if the Host header is one of this server's own loopback
    names. A missing Host is rejected: HTTP/1.1 requires it and every
    real client (browser, curl, urllib) sends it, so its absence signals
    a hand-crafted request that shouldn't slip past this check."""
    if not host_header:
        return False
    return host_header in allowed_hosts(port)


def allowed_origins(port: int) -> frozenset[str]:
    return frozenset(f"http://{host}" for host in allowed_hosts(port))


def origin_allowed(origin: str | None, referer: str | None, port: int) -> bool:
    """Defense against a malicious page fetch()ing state-changing
    endpoints. Reject only when an Origin (preferred) or Referer header
    is present AND doesn't name this server; a plain non-browser client
    (curl, tests) that sends neither is allowed through -- the Host and
    token checks are what constrain those. Compared against the KNOWN
    bound port, never the request's own Host header."""
    origins = allowed_origins(port)
    for value in (origin, referer):
        if value:
            parts = urlsplit(value)
            return f"{parts.scheme}://{parts.netloc}" in origins
    return True


def new_session_token() -> str:
    """A fresh, unguessable per-launch token. token_urlsafe(32) is 256
    bits of CSPRNG output -- not brute-forceable over a localhost socket."""
    return secrets.token_urlsafe(32)


def token_matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison so a wrong token can't be narrowed down
    by response-timing. A missing/blank token never matches."""
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)
