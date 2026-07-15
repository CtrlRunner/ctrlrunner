"""
Longest-processing-time-first (LPT) greedy bin-packing across workers,
using each test's historical median duration as its weight -- replacing
plain round-robin chunking so five slow tests don't all land on one
worker while forty fast ones sit on another.

Deliberately simple: LPT is a well-understood, deterministic heuristic.
The goal is "stop the obviously bad case," not optimal scheduling.
"""

import statistics


def _lpt_shard_weighted(items: list[tuple], num_bins: int) -> list[list]:
    """Generic LPT greedy bin-packer over (item, weight) pairs. With
    all-equal weights, Python's stable sort plus greedy first-min-bin
    assignment degenerates to round-robin in input order -- the property
    lpt_shard's no-history guarantee (and group_aware_shard's
    fully-parallel degeneration guarantee) both rest on."""
    if not items:
        return []

    ordered = sorted(items, key=lambda pair: pair[1], reverse=True)

    n = max(1, min(num_bins, len(items)))
    bins: list[list] = [[] for _ in range(n)]
    bin_loads = [0.0] * n

    for item, weight in ordered:
        idx = bin_loads.index(min(bin_loads))
        bins[idx].append(item)
        bin_loads[idx] += weight

    return [b for b in bins if b]


def duration_weights(keys, durations: dict) -> list[tuple]:
    """(key, weight) pairs for _lpt_shard_weighted: a known median is
    used as-is; None/absent gets the overall median of whatever IS
    known as a neutral placeholder -- never zero, since a zero-weight
    placeholder would cluster every new/unknown test onto one worker.

    `durations.get(tid) or fallback` falsy-coerces a real 0.0
    median (a genuinely fast/instant test) into "no history," wrongly
    applying the fallback weight instead. Only None/absent means "no
    history" -- an explicit None-check is required so 0.0 stays 0.0."""
    known = [d for d in durations.values() if d is not None]
    fallback = statistics.median(known) if known else 1.0

    weighted = []
    for key in keys:
        duration = durations.get(key)
        weighted.append((key, duration if duration is not None else fallback))
    return weighted


def lpt_shard(
    test_ids: list[str], num_workers: int, durations: dict[str, float | None]
) -> list[list[str]]:
    """durations: test_id -> known median duration, or None/absent for a
    test with no history yet (see duration_weights for the fallback
    rules). With NO history at all (every duration unknown), every test
    gets the same fallback weight and the packing degenerates to exactly
    round-robin order, so an empty/fresh history store changes nothing."""
    return _lpt_shard_weighted(duration_weights(test_ids, durations), num_workers)


def lookup_median_durations(
    test_ids: list[str], history_store, project: str | None, window: int
) -> dict[str, float | None]:
    """One history query per test -- fine at real suite sizes (this runs
    once per invocation, not per test execution), and keeps the lookup
    itself trivially testable/mockable independent of SQLite specifics."""
    result = {}
    for test_id in test_ids:
        durations = history_store.get_durations(test_id, project=project, window=window)
        result[test_id] = statistics.median(durations) if durations else None
    return result
