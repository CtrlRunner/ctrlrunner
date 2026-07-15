"""
Fail policies.

A single mutable FailPolicyState is shared across every Orchestrator
instance in a run (including every project's own Orchestrator in a
multi-project run via run_projects()) so --max-failures/--max-timeouts
count across the WHOLE invocation, not reset per project.

Reuses the existing cancel_event mechanism built for UI Mode's Cancel
button -- crossing a threshold just calls cancel_event.set(), exactly
as if the user had clicked Stop. No new kill path.
"""

from dataclasses import dataclass


@dataclass
class FailPolicyState:
    max_failures: int = 0  # 0 = unlimited
    max_timeouts: int = 0  # 0 = unlimited
    stop_on_worker_crash: bool = False

    failure_count: int = 0
    timeout_count: int = 0
    cancel_reason: str | None = None  # None = no policy has fired (a plain external
    # cancel, if any, has no policy reason)

    def is_active(self) -> bool:
        return bool(self.max_failures or self.max_timeouts or self.stop_on_worker_crash)

    def record_failure(self) -> str | None:
        """Call once per Result with outcome == 'failed' (including
        timeout-kills, which are also 'failed'). Returns a trigger
        reason string if this crossed the threshold, else None."""
        self.failure_count += 1
        if self.max_failures and self.failure_count >= self.max_failures:
            return "max_failures"
        return None

    def record_timeout(self) -> str | None:
        """Call once per hard-kill-due-to-timeout specifically (a
        subset of failures -- a timeout is always also a failure, but
        not every failure is a timeout)."""
        self.timeout_count += 1
        if self.max_timeouts and self.timeout_count >= self.max_timeouts:
            return "max_timeouts"
        return None

    def record_worker_crash(self) -> str | None:
        if self.stop_on_worker_crash:
            return "stop_on_worker_crash"
        return None


def resolve_fail_policy(
    config: dict,
    cli_max_failures=None,
    cli_max_timeouts=None,
    cli_fail_fast: bool = False,
    cli_stop_on_worker_crash: bool = False,
) -> FailPolicyState:
    """CLI > config > built-in default (0/0/False), same precedence as
    everywhere else. --fail-fast is sugar for --max-failures 1 and is
    itself a CLI-level input, so it outranks a config-file max_failures
    exactly the way an explicit --max-failures would -- only an
    explicit cli_max_failures value (including 0, "explicitly
    unlimited") wins over it."""
    section = config.get("fail_policy", {}) or {}

    raw_max_failures = section.get("max_failures", 0)
    if not isinstance(raw_max_failures, int) or isinstance(raw_max_failures, bool):
        raise ValueError(
            f"[pyrunner.fail_policy].max_failures must be an integer, got {raw_max_failures!r}"
        )
    raw_max_timeouts = section.get("max_timeouts", 0)
    if not isinstance(raw_max_timeouts, int) or isinstance(raw_max_timeouts, bool):
        raise ValueError(
            f"[pyrunner.fail_policy].max_timeouts must be an integer, got {raw_max_timeouts!r}"
        )
    raw_stop_on_crash = section.get("stop_on_worker_crash", False)
    if not isinstance(raw_stop_on_crash, bool):
        raise ValueError(
            f"[pyrunner.fail_policy].stop_on_worker_crash must be a boolean, got {raw_stop_on_crash!r}"
        )

    if cli_max_failures is not None:
        max_failures = cli_max_failures
    elif cli_fail_fast:
        max_failures = 1
    else:
        max_failures = raw_max_failures

    max_timeouts = cli_max_timeouts if cli_max_timeouts is not None else raw_max_timeouts
    stop_on_worker_crash = cli_stop_on_worker_crash or raw_stop_on_crash

    return FailPolicyState(
        max_failures=max_failures,
        max_timeouts=max_timeouts,
        stop_on_worker_crash=stop_on_worker_crash,
    )
