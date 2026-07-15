"""
A versioned, serializable event envelope -- the stable public shape for anything
that needs to observe a run from outside the orchestrator (hooks,
plugins, a future IDE integration), as opposed to Result/TestItem/the
internal multiprocessing tuples, which stay free to change every
release.

Two-tier design: the internal multiprocessing IPC format (plain tuples
in orchestrator.py/worker.py) is untouched and stays free to change --
it's a hot path, and EventEnvelope overhead there would be pure cost for
no consumer's benefit. The orchestrator builds an EventEnvelope at each
lifecycle point and hands it to every registered EventSubscriber.

ConsoleReporter (reporters.py) is unchanged and unaffected -- it keeps
receiving its own simple, positional-argument method calls exactly as
before (on_run_start, on_test_start, on_test_end, on_run_end);
EventSubscriber is a new, separate, envelope-based interface, so
existing line/dots/json reporters (and anyone else's ConsoleReporter
subclass) need zero changes. This is the corrected design from the
original plan draft, which would have changed ConsoleReporter's method
signatures -- a breaking change to a shipped interface.
"""

from dataclasses import dataclass

# Event payloads now use the exact same camelCase key names as
# the JSON reporter's per-test entries -- one schema for streaming and
# reporting, produced by one function (result_to_public_dict below),
# instead of two independently-shaped payloads that this design
# explicitly forbade. v1 shipped snake_case payload keys ("test_id",
# "retries_configured", ...), so this rename is the breaking change the
# version field exists for.
SCHEMA_VERSION = 2

# Additive payload keys are fine within a schema version; a breaking
# change (renamed/removed key, changed type) bumps SCHEMA_VERSION.
# Subscribers MUST ignore unknown types, which is what makes adding
# future event types (project_start, ...) non-breaking by construction.
# (worker_crashed was considered here but shipped instead as
# worker_terminated's reason="crashed" -- no new event type needed.)
EVENT_TYPES = frozenset(
    {
        "run_start",
        "test_start",
        "test_end",
        "run_end",
        "worker_spawned",
        "worker_terminated",
    }
)


@dataclass
class EventEnvelope:
    type: str
    timestamp: float
    payload: dict
    project: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        # EVENT_TYPES was declared but never enforced -- without
        # this, a typo'd event type would silently ship to every
        # subscriber instead of failing loudly at the one place (the
        # construction site) that could catch it early.
        if self.type not in EVENT_TYPES:
            raise ValueError(
                f"Unknown EventEnvelope type {self.type!r}; must be one of "
                f"{sorted(EVENT_TYPES)}"
            )

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "type": self.type,
            "timestamp": self.timestamp,
            "project": self.project,
            "payload": self.payload,
        }


def result_to_public_dict(result) -> dict:
    """THE public serialization of one test Result -- the single source
    of truth for both the JSON reporter's per-test entries and the
    `test_end` event payload (one schema for streaming and reporting;
    these two used to be built independently and had already diverged
    in both key style and field coverage).
    camelCase keys, matching every other machine-readable surface here
    (the envelope's own "schemaVersion", the JSON reporter's stats).
    Takes any Result-like object (duck-typed) so this module stays free
    of reporter imports."""
    return {
        "id": result.test_id,
        "caseId": result.case_id,
        "tags": sorted(result.tags),
        "outcome": result.outcome,
        "duration": round(result.duration, 3),
        "attempts": result.attempts,
        "error": result.error,
        "artifacts": list(result.artifacts),
        "steps": result.steps,
        "groups": dict(result.groups),
        "properties": dict(result.properties),
        "project": result.project,
        "quarantined": result.quarantined,
        "quarantineReason": result.quarantine_reason,
        "workerRestartOverhead": result.worker_restart_overhead,
        "retriesConfigured": result.retries_configured,
        "workerId": result.worker_id,
        "nearTimeout": result.near_timeout,
        "assertDetails": result.assert_details,
        "logs": result.logs,
        # Runner-synthesized infrastructure failure (timeout
        # hard-kill / worker crash) vs a genuine test failure. getattr
        # keeps duck-typed Result-likes without the field working.
        "infraError": getattr(result, "infra_error", False),
        "warnings": getattr(result, "warnings", None),
        "flaky": getattr(result, "flaky", False),
        "startedAt": getattr(result, "started_at", None),
    }


class EventSubscriber:
    """The stable, envelope-based observation interface -- what hooks
    and reporter-category plugins will subscribe through once they
    exist. Register via
    Orchestrator(..., event_subscribers=[...]).

    Unknown event `type`s MUST be ignored (not raise, not log an
    error) -- that's what makes adding a future event type additive
    rather than breaking for every existing subscriber."""

    def on_event(self, event: EventEnvelope) -> None:
        raise NotImplementedError
