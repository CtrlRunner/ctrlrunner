"""
Best-effort redaction of obvious secrets from captured test logs before
they're written into shareable reports (OWASP A09).

When --logs is on, everything a test prints -- including credentials,
bearer tokens, or API keys that a Playwright test happens to log -- is
captured verbatim and embedded into results.json, the HTML report, and
JUnit XML, all of which are commonly uploaded to CI dashboards. This
module masks the most obvious secret shapes so they don't propagate into
those artifacts by accident.

Scope and limits, stated plainly: this is a safety net, not a guarantee.
A pattern set can only catch shapes it knows about; treat reports
containing captured logs as sensitive regardless. Redaction runs in the
orchestrator (parent) process when it receives a worker's finished-test
message, so it needs no plumbing into the worker subprocess and never has
to serialize compiled patterns across a spawn.

Configuration ([ctrlrunner.log_redaction] in ctrlrunner.toml):

    [ctrlrunner.log_redaction]
    enabled = true                 # default; false disables redaction entirely
    patterns = ["MYCORP-[0-9]+"]    # extra regexes, applied on top of the built-ins
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# Case-insensitive shapes for the most common secret leaks. Each pattern
# is written so the WHOLE match is the sensitive span -- it's replaced
# wholesale with [REDACTED], so a matched "password=hunter2" becomes
# "[REDACTED]" rather than leaking the value.
DEFAULT_REDACTION_PATTERNS: tuple[str, ...] = (
    r"(?i)\b(?:authorization|auth)\s*[:=]\s*bearer\s+[\w.\-]+",
    r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}",
    r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)"
    r"\s*[:=]\s*\S+",
    r"AKIA[0-9A-Z]{16}",  # AWS access key id
    r"gh[pousr]_[A-Za-z0-9]{20,}",  # GitHub personal/OAuth/app tokens
)


def resolve_redaction_patterns(config: dict) -> list[re.Pattern] | None:
    """Reads [ctrlrunner.log_redaction]. Returns compiled patterns (built-in
    defaults plus any configured extras), or None when redaction is
    disabled. Raises ValueError on malformed config, matching the other
    resolve_*() helpers' fail-loud-on-bad-config posture."""
    section = config.get("log_redaction", {}) or {}

    enabled = section.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"[ctrlrunner.log_redaction].enabled must be a boolean, got {enabled!r}")
    if not enabled:
        return None

    extra = section.get("patterns", [])
    if not (isinstance(extra, list) and all(isinstance(p, str) for p in extra)):
        raise ValueError(
            f"[ctrlrunner.log_redaction].patterns must be a list of strings, got {extra!r}"
        )

    compiled = []
    for raw in (*DEFAULT_REDACTION_PATTERNS, *extra):
        try:
            compiled.append(re.compile(raw))
        except re.error as e:
            raise ValueError(
                f"[ctrlrunner.log_redaction].patterns: invalid regex {raw!r}: {e}"
            ) from e
    return compiled


def redact_text(text: str | None, patterns: list[re.Pattern]) -> str | None:
    if not text:
        return text
    for pat in patterns:
        text = pat.sub(REDACTED, text)
    return text


def redact_log_entries(logs, patterns: list[re.Pattern] | None):
    """Applies redaction to a worker's per-attempt log list (the shape
    log_capture.capture_logs() produces: stdout/stderr strings plus a
    list of record dicts). Returns the input unchanged when there's
    nothing to do, so callers can pass it through unconditionally."""
    if not logs or not patterns:
        return logs
    for entry in logs:
        if "stdout" in entry:
            entry["stdout"] = redact_text(entry["stdout"], patterns)
        if "stderr" in entry:
            entry["stderr"] = redact_text(entry["stderr"], patterns)
        for record in entry.get("records", []):
            if "message" in record:
                record["message"] = redact_text(record["message"], patterns)
    return logs
