# Security model

pyrunner is a local test runner. This document states what it does and
doesn't defend against, and how the hardening in the codebase maps to a
concrete threat model, so a reader can reason about the tool rather than
guess.

## Threat model

pyrunner **executes arbitrary local test code by design.** Discovering
and running the test files in your project is the whole job, so "an
attacker who can write your test files" is out of scope — at that point
they already have code execution as you. The adversaries that matter are:

1. **A malicious web page** in a browser you have open, trying to reach
   pyrunner's local HTTP servers (UI Mode, `show-report`) and either
   drive them (start runs, cancel, load traces) or read what they serve.
2. **Another local user or process** on a shared machine or CI runner,
   trying to reach those same servers or read pyrunner's on-disk state.
3. **Untrusted data flowing into reports** — test output, error text,
   artifact filenames — reaching a browser or a shared CI dashboard.

## The local HTTP servers

Both the UI Mode server (`pyrunner ui`) and the report server
(`pyrunner show-report`) bind `127.0.0.1` only. Binding loopback is *not*
by itself a browser-security boundary: any page can `fetch()` a localhost
port, and DNS rebinding can make an attacker hostname resolve to
`127.0.0.1` so the browser treats the request as same-site. The shared
defenses (in [`pyrunner/ui/localsec.py`](../pyrunner/ui/localsec.py)) are:

- **Host allowlisting** — every request's `Host` header must be one of
  this server's own loopback names (`127.0.0.1:<port>`, `localhost:<port>`,
  `[::1]:<port>`). A rebound request carries the attacker's hostname in
  `Host`, so it's rejected. Applied to **every** request, GET included.
- **True-origin validation** — state-changing requests validate any
  `Origin`/`Referer` against the server's *own* bound port, never against
  the request's own `Host` header (echoing `Host` was a real bypass: set
  both to the same attacker value and they trivially matched).
- **Per-session token** — the UI server mints an unguessable token at
  launch, embeds it in the served page, and requires it (in the
  `X-Pyrunner-Token` header) on every state-changing POST. A page that
  never received the token — a cross-site attacker, or a different local
  process/user — can't forge it. (The SSE stream and other GETs don't
  require it: `EventSource` can't set headers, and GETs are read-only and
  already protected from cross-origin reads by the same-origin policy plus
  Host allowlisting.)
- **`show-report` symlink containment** — the static server resolves each
  requested path (following symlinks) and refuses anything that escapes
  the served report directory. `..` is already blocked by the stdlib, but
  it does not resolve symlinks; this closes that gap.

### Binding a non-loopback address

Both commands default to `127.0.0.1` and **refuse** a non-loopback
`--bind` unless you also pass `--allow-remote`. The access controls above
are appropriate for loopback; exposing these servers on a routable
interface hands that surface to anyone who can reach the port. Only use
`--allow-remote` in a trusted, isolated environment.

## On-disk state

- **History database** (`reports/.history.db`) is created `0o600`
  (owner-only) on POSIX. On a shared workspace, prefer a per-job
  `[pyrunner.history].db_path` so jobs don't share timing history.
- **Report/coverage directories** are pruned/purged with containment
  guards that refuse to delete anything outside their expected root.

## Captured logs may contain secrets

With `--logs on` (or `only-on-failure`), everything a test prints is
captured and embedded into `results.json`, the HTML report, and JUnit
XML — artifacts often uploaded to CI dashboards. pyrunner applies
**best-effort redaction** of obvious secret shapes (passwords, bearer
tokens, API keys; see
[`pyrunner/reporting/log_redaction.py`](../pyrunner/reporting/log_redaction.py))
before logs reach any report, configurable under `[pyrunner.log_redaction]`.

**This is a safety net, not a guarantee.** A pattern set only catches
shapes it knows about. Treat any report containing captured logs as
sensitive, and add project-specific `patterns` for secret formats unique
to your codebase.

## Report rendering (XSS)

The HTML report and UI frontend build the DOM exclusively via
`document.createElement` + `textContent`/`createTextNode`; `innerHTML` is
only ever assigned constant empty strings. Worker-controlled strings
(test ids, errors, log output) are inserted as text, never markup.
Artifact hrefs are scheme-sanitized on both the Python and JS sides
(only relative paths and `http`/`https`/`file` become clickable links).

## `--changed-since` and git

The user-supplied git ref passed to `--changed-since` is run through an
argument list (never a shell) and is additionally guarded with an
end-of-options `--` separator plus a rejection of refs beginning with
`-`, so it can't be smuggled in as a `git diff` option.
