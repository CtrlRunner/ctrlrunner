"""
Flaky analytics.

"Flaky" is already latent in existing history data: a run where
attempts > 1 and the final outcome is "passed" means "failed at least
once, passed on retry." flake_score is the fraction of a test's recent
retries-configured runs that ended up flaky by that definition:

    flake_score = (runs where attempts > 1 AND outcome == "passed")
                  / (runs where retries were configured at all)

Surfaced via `ctrlrunner flaky-report` -- a deliberately SEPARATE command
from the normal test-run path, so acting on this data (quarantining a
test) is an explicit, human-reviewed step, never automatic.
"""

import json as json_module
from dataclasses import dataclass


@dataclass
class FlakyStats:
    test_id: str
    project: str | None
    flake_score: float | None  # None = no eligible sample (never retried-and-configured)
    sample_size: int
    quarantined: bool
    quarantine_reason: str | None
    # True when quarantined AND flake_score has dropped low enough that
    # it might be worth reviewing whether quarantine is still needed --
    # an informational nudge only, mitigating the
    # "stale quarantine list nobody revisits" risk. Never auto-removes.
    consider_unquarantine: bool = False


def compute_flake_score(outcome_rows: list[dict]) -> tuple[float | None, int]:
    """outcome_rows: HistoryStore.get_outcomes()'s own shape. Returns
    (flake_score, sample_size). sample_size counts only rows where
    retries were actually configured (retries_configured truthy) --
    a test that's never had retries configured has no eligible sample
    and gets flake_score=None, not 0.0 (which would misleadingly imply
    "definitely not flaky" rather than "we don't know")."""
    eligible = [r for r in outcome_rows if r.get("retries_configured")]
    if not eligible:
        return None, 0
    flaky_count = sum(
        1
        for r in eligible
        if r.get("attempts") and r["attempts"] > 1 and r.get("outcome") == "passed"
    )
    return flaky_count / len(eligible), len(eligible)


# Below this flake_score, a quarantined test is flagged as maybe-fixed --
# purely informational, never auto-un-quarantined.
_UNQUARANTINE_CONSIDERATION_THRESHOLD = 0.05


def compute_flaky_report(
    history_store, quarantine_config=None, project: str | None = None, window: int = 20
) -> list[FlakyStats]:
    """One row per test_id with history, sorted most-flaky-first (an
    unknown/no-sample score sorts last, not first, so an obviously
    risky test never gets buried under a pile of never-retried ones)."""
    quarantined_ids = quarantine_config.test_ids if quarantine_config else set()
    reason = quarantine_config.reason if quarantine_config else None

    stats = []
    for test_id in history_store.list_test_ids(project=project):
        rows = history_store.get_outcomes(test_id, project=project, window=window)
        score, sample_size = compute_flake_score(rows)
        is_quarantined = test_id in quarantined_ids
        consider_unquarantine = (
            is_quarantined
            and score is not None
            and score < _UNQUARANTINE_CONSIDERATION_THRESHOLD
            and sample_size >= 5  # don't suggest this off a tiny sample
        )
        stats.append(
            FlakyStats(
                test_id=test_id,
                project=project,
                flake_score=score,
                sample_size=sample_size,
                quarantined=is_quarantined,
                quarantine_reason=reason if is_quarantined else None,
                consider_unquarantine=consider_unquarantine,
            )
        )

    stats.sort(key=lambda s: (s.flake_score is None, -(s.flake_score or 0.0)))
    return stats


def format_flaky_report(stats: list[FlakyStats], fmt: str = "text") -> str:
    if fmt == "json":
        return json_module.dumps(
            [
                {
                    "testId": s.test_id,
                    "project": s.project,
                    "flakeScore": s.flake_score,
                    "sampleSize": s.sample_size,
                    "quarantined": s.quarantined,
                    "quarantineReason": s.quarantine_reason,
                    "considerUnquarantine": s.consider_unquarantine,
                }
                for s in stats
            ],
            indent=2,
        )

    if not stats:
        return "No history data found -- run tests at least a few times first."

    lines = []
    for s in stats:
        score_str = f"{s.flake_score:.0%}" if s.flake_score is not None else "n/a"
        line = f"{score_str:>5}  (n={s.sample_size:<3})  {s.test_id}"
        if s.quarantined:
            line += f"  [quarantined: {s.quarantine_reason or 'no reason given'}]"
        if s.consider_unquarantine:
            line += "  -- flake score has dropped; consider un-quarantining"
        lines.append(line)
    return "\n".join(lines)
