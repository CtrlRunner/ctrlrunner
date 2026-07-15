"""
Quarantine.

A config-driven allowlist, populated by a human after reviewing
`ctrlrunner flaky-report` output -- never fully automatic. A quarantined
test still runs (visibility preserved -- quarantine is not skip()),
but a failure on it is reported as the distinct 'quarantined_failure'
outcome rather than 'failed', so it doesn't count toward
--max-failures/--max-timeouts or the process exit code. A pass stays
an ordinary 'passed'.
"""

from dataclasses import dataclass, field


@dataclass
class QuarantineConfig:
    test_ids: set[str] = field(default_factory=set)
    reason: str | None = None

    def is_quarantined(self, test_id: str) -> bool:
        return test_id in self.test_ids


def resolve_quarantine_config(config: dict) -> QuarantineConfig | None:
    """Returns None if [ctrlrunner.quarantine] is absent entirely -- zero
    behavior change, matching every other opt-in section in this
    project."""
    section = config.get("quarantine")
    if not section:
        return None
    test_ids = section.get("test_ids", [])
    if not isinstance(test_ids, (list, tuple)):
        raise ValueError(
            f"[ctrlrunner.quarantine].test_ids must be a list of test id strings, got {test_ids!r}"
        )
    reason = section.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError(f"[ctrlrunner.quarantine].reason must be a string, got {reason!r}")
    return QuarantineConfig(test_ids=set(test_ids), reason=reason)
