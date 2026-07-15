"""Worker-count resolution and scoped worker-budget planning.

`num_workers` accepts three spellings everywhere it can be set (CLI -n,
[ctrlrunner] in ctrlrunner.toml, [ctrlrunner.projects.<name>], the UI):

  - a positive int: used as-is,
  - "auto": max(1, CPUs - 1) -- leaves one core of headroom for the
    orchestrator/UI process,
  - "N%" (e.g. "50%"): max(1, CPUs * N // 100); values over 100 are
    allowed for deliberate oversubscription.

"auto" is the default when nothing is configured.
"""

from __future__ import annotations

import fnmatch
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

_PERCENT_RE = re.compile(r"(\d+)%")


def _cpu_count() -> int:
    # process_cpu_count (3.13+) respects affinity/cgroup limits;
    # cpu_count is the fallback on 3.12.
    fn = getattr(os, "process_cpu_count", None) or os.cpu_count
    return fn() or 1


def resolve_num_workers(value) -> int:
    """Resolve a num_workers setting to a concrete positive int.

    Idempotent on ints, so every layer can call it defensively without
    tracking whether the value was already resolved.
    """
    if value is None or value == "auto":
        return max(1, _cpu_count() - 1)
    # bool is an int subclass (TOML `true` arrives as one) -- reject it
    # before the int check.
    if isinstance(value, bool):
        raise ValueError(f"num_workers must be a positive integer, 'auto', or 'N%', got {value!r}")
    if isinstance(value, int):
        if value < 1:
            raise ValueError(
                f"num_workers must be a positive integer, 'auto', or 'N%', got {value!r}"
            )
        return value
    if isinstance(value, str):
        match = _PERCENT_RE.fullmatch(value)
        if match:
            percent = int(match.group(1))
            if percent >= 1:
                return max(1, _cpu_count() * percent // 100)
    raise ValueError(f"num_workers must be a positive integer, 'auto', or 'N%', got {value!r}")


@dataclass(frozen=True)
class WorkerConstraint:
    """A resolved worker budget for one group of tests."""

    group: str  # config: raw [ctrlrunner.workers] key; decorator: "relpath.py::ClassName"
    count: int  # >= 1
    mode: str = "cap"  # "cap" | "dedicated"


@dataclass(frozen=True)
class WorkerConstraintSpec:
    """One parsed [ctrlrunner.workers] entry, before matching against tests."""

    path_pattern: str
    class_name: str | None
    count: int
    mode: str
    order: int  # declaration order (TOML preserves it) -- specificity tie-breaker


def load_worker_constraints(config: dict) -> list[WorkerConstraintSpec]:
    """Parses the [ctrlrunner.workers] table out of an already-loaded
    [ctrlrunner] config dict (load_config returns just that inner table,
    so like [ctrlrunner.grouping], a bare top-level [workers] table is
    silently invisible -- it must be written as [ctrlrunner.workers]).

    Keys are "path", "path glob", or "path::ClassName"; values are a
    plain int (cap mode) or an inline table {count=N, mode="cap"|
    "dedicated"}. Group counts must be concrete ints -- "auto"/"N%"
    have no defined meaning relative to a single group's budget.
    """
    table = config.get("workers")
    if table is None:
        return []
    if not isinstance(table, dict):
        raise ValueError(
            f"[ctrlrunner.workers] must be a table of 'path' or 'path::ClassName' keys, got {table!r}"
        )

    specs: list[WorkerConstraintSpec] = []
    for order, (raw_key, value) in enumerate(table.items()):
        key = str(raw_key)  # TOML keys are always strings; pinned for the type checker
        path_pattern, sep, class_name = key.partition("::")
        if not path_pattern or (sep and not class_name):
            raise ValueError(
                f"[ctrlrunner.workers] key {key!r} is malformed -- expected "
                f"'path' or 'path::ClassName'"
            )

        if isinstance(value, bool):
            raise ValueError(
                f"[ctrlrunner.workers] {key!r}: count must be an integer >= 1, got {value!r}"
            )
        if isinstance(value, int):
            count, mode = value, "cap"
        elif isinstance(value, dict):
            unknown = set(value) - {"count", "mode"}
            if unknown:
                raise ValueError(
                    f"[ctrlrunner.workers] {key!r}: unknown key(s) "
                    f"{', '.join(sorted(unknown))} -- allowed: count, mode"
                )
            if "count" not in value:
                raise ValueError(f"[ctrlrunner.workers] {key!r}: missing required 'count'")
            count = value.get("count")
            mode_value = value.get("mode", "cap")
            if isinstance(count, bool) or not isinstance(count, int):
                raise ValueError(
                    f"[ctrlrunner.workers] {key!r}: count must be an integer >= 1, got {count!r}"
                )
            if mode_value not in ("cap", "dedicated"):
                raise ValueError(
                    f"[ctrlrunner.workers] {key!r}: mode must be 'cap' or 'dedicated', "
                    f"got {mode_value!r}"
                )
            mode = "dedicated" if mode_value == "dedicated" else "cap"
        else:
            raise ValueError(
                f"[ctrlrunner.workers] {key!r}: value must be an integer >= 1 or a "
                f"table {{count=N, mode=...}}, got {value!r}"
            )

        if count < 1:
            raise ValueError(
                f"[ctrlrunner.workers] {key!r}: count must be an integer >= 1, got {count!r}"
            )

        specs.append(
            WorkerConstraintSpec(
                path_pattern=path_pattern,
                class_name=class_name or None,
                count=count,
                mode=mode,
                order=order,
            )
        )
    return specs


def _normalized_path(source_path) -> str:
    """Posix path used for [ctrlrunner.workers] matching: relative to cwd
    when the file lives under it, else the resolved absolute path."""
    path = Path(source_path).resolve()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _specificity(spec: WorkerConstraintSpec, exact: bool) -> int:
    # Lower wins: class-qualified exact path (0) -> class-qualified glob
    # (1) -> exact file (2) -> glob (3).
    if spec.class_name is not None:
        return 0 if exact else 1
    return 2 if exact else 3


def assign_worker_groups(tests, specs: list[WorkerConstraintSpec]):
    """Maps each test id to its WorkerConstraint (tests without one are
    absent). The most specific matching [ctrlrunner.workers] spec wins;
    on a specificity tie, the first-declared spec wins. A config match
    always beats a @test_class(workers=...) decorator."""
    result: dict[str, WorkerConstraint] = {}
    path_cache: dict[str, str] = {}

    for item in tests:
        if item.source_path is None:
            norm = ""
        else:
            raw = str(item.source_path)
            norm = path_cache.get(raw)
            if norm is None:
                norm = _normalized_path(item.source_path)
                path_cache[raw] = norm

        best: tuple[int, int] | None = None
        best_spec: WorkerConstraintSpec | None = None
        for spec in specs:
            if spec.class_name is not None and spec.class_name != item.class_name:
                continue
            exact = norm == spec.path_pattern
            if not exact and not fnmatch.fnmatch(norm, spec.path_pattern):
                continue
            rank = (_specificity(spec, exact), spec.order)
            if best is None or rank < best:
                best, best_spec = rank, spec

        if best_spec is not None:
            key = (
                f"{best_spec.path_pattern}::{best_spec.class_name}"
                if best_spec.class_name is not None
                else best_spec.path_pattern
            )
            result[item.id] = WorkerConstraint(
                group=key, count=best_spec.count, mode=best_spec.mode
            )
        elif item.workers is not None:
            result[item.id] = WorkerConstraint(
                group=f"{norm}::{item.class_name}",
                count=item.workers,
                mode=item.workers_mode or "cap",
            )

    return result


@dataclass(frozen=True)
class ExecUnit:
    """The schedulable atom: an ordered list of test ids that must stay
    together in one worker process.

    kind:
      - "serial": a @test_class(serial=True) group -- atomic, definition
        order, skip-on-fail, retried together (serial_retries budget).
      - "file": the default grouping -- a file's non-serial tests run in
        definition order in one worker, with no skip-on-fail coupling.
      - "single": a fully-parallel test scheduled on its own.
    """

    key: str  # serial: the serial_group; file: "file::<path>[::<group>]"; single: test id
    kind: str  # "serial" | "file" | "single"
    test_ids: tuple[str, ...]
    serial_retries: int = 0


def build_units(tests, constraints_by_id, fully_parallel_default: bool):
    """Partitions selected tests (in registry = definition order) into
    ExecUnits, and maps each unit key to its members' WorkerConstraint.

    Serial classes are always their own units, extracted from their
    file, so the group-retry boundary coincides exactly with the atomic
    unit. File units are pre-split on constraint boundaries: a
    class-qualified [ctrlrunner.workers] entry pulls that class's tests
    out of the file's pool unit into its own constrained unit.
    """
    members: dict[str, list[str]] = {}
    kinds: dict[str, str] = {}
    retries: dict[str, int] = {}
    constraints_by_unit: dict[str, WorkerConstraint] = {}
    path_cache: dict[str, str] = {}

    for item in tests:
        constraint = constraints_by_id.get(item.id)

        if item.serial_group is not None:
            key, kind = item.serial_group, "serial"
        else:
            effective_fp = (
                item.fully_parallel if item.fully_parallel is not None else fully_parallel_default
            )
            if effective_fp:
                key, kind = item.id, "single"
            else:
                raw = str(item.source_path) if item.source_path is not None else ""
                norm = path_cache.get(raw)
                if norm is None:
                    norm = _normalized_path(item.source_path) if raw else ""
                    path_cache[raw] = norm
                key = f"file::{norm}"
                if constraint is not None:
                    key = f"{key}::{constraint.group}"
                kind = "file"

        bucket = members.get(key)
        if bucket is None:
            members[key] = [item.id]
            kinds[key] = kind
            retries[key] = item.serial_retries if kind == "serial" else 0
        else:
            bucket.append(item.id)
        if constraint is not None and key not in constraints_by_unit:
            # Members of one unit share a constraint by construction
            # (file units are split on constraint boundaries; serial/
            # single units are class/test scoped) -- first member wins.
            constraints_by_unit[key] = constraint

    units = [
        ExecUnit(key=key, kind=kinds[key], test_ids=tuple(ids), serial_retries=retries[key])
        for key, ids in members.items()
    ]
    return units, constraints_by_unit


_VALID_ORDERS = ("declared", "alpha", "random")


def order_units(units: list[ExecUnit], order: str, seed: int | None) -> list[ExecUnit]:
    """Reorders ExecUnits -- NEVER the tests inside one -- so a serial
    group's members and a file's tests keep their internal definition
    order regardless of --order. This only changes which unit a worker
    picks up first/next; group_aware_shard's LPT packing (stable sort)
    still re-sorts by weight, but a stable sort preserves THIS relative
    order among equal-weight units, which is the common case with no
    history yet -- so --order genuinely changes observed scheduling.

    - "declared": no-op, returns `units` unchanged (today's behavior:
      registration/selection order).
    - "alpha": sorted by unit.key -- deterministic across runs/
      registration-order changes, independent of history/seed.
    - "random": shuffled with random.Random(seed). Caller must resolve
      a real int seed before calling (see cli.py's --seed resolution);
      this function never invents one, so the same call always produces
      the same order for the same seed.
    """
    if order == "declared":
        return units
    if order == "alpha":
        return sorted(units, key=lambda u: u.key)
    if order == "random":
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("order_units('random', ...) requires an int seed")
        shuffled = list(units)
        random.Random(seed).shuffle(shuffled)
        return shuffled
    raise ValueError(f"Unknown order {order!r}; must be one of {_VALID_ORDERS}")


@dataclass
class Batch:
    """One worker process's workload: an ordered list of ExecUnits.
    `group`/`dedicated` carry the WorkerConstraint the batch was sharded
    under, so requeue-after-kill can preserve the budget label."""

    units: list[ExecUnit]
    group: str | None = None
    dedicated: bool = False

    @property
    def test_ids(self) -> list[str]:
        return [tid for unit in self.units for tid in unit.test_ids]


@dataclass
class ShardPlan:
    batches: list[Batch]
    reservations: dict[str, int]  # dedicated group -> clamped slot count


def _unit_weights(units, durations) -> list[tuple]:
    """(unit, weight) pairs; a unit's weight is the sum of its members'
    durations, with the same per-test fallback rules as lpt_shard."""
    from ctrlrunner.execution.sharding import duration_weights

    all_ids = [tid for unit in units for tid in unit.test_ids]
    per_test = dict(duration_weights(all_ids, durations or {}))
    return [(unit, sum(per_test[tid] for tid in unit.test_ids)) for unit in units]


def group_aware_shard(
    units,
    constraints_by_unit: dict[str, WorkerConstraint],
    num_workers: int,
    durations=None,
    warn=None,
) -> ShardPlan:
    """Shards ExecUnits into worker batches under scoped constraints.

    Cap mode needs no scheduler cooperation at all: a group LPT-packed
    into <= N batches can never occupy more than N workers at once.
    Dedicated mode records a reservation per group; the scheduler's
    spawn-eligibility check enforces it (see orchestrator).

    Dedicated reservations that don't fit the pool are clamped in
    declaration order (each floored at 1, one warning), never an error.
    """
    from ctrlrunner.execution.sharding import _lpt_shard_weighted

    if not units:
        return ShardPlan(batches=[], reservations={})

    # Partition units by constraint group, preserving input order.
    grouped: dict[str, list] = {}
    group_constraint: dict[str, WorkerConstraint] = {}
    pool = []
    for unit in units:
        constraint = constraints_by_unit.get(unit.key)
        if constraint is None:
            pool.append(unit)
        else:
            grouped.setdefault(constraint.group, []).append(unit)
            group_constraint.setdefault(constraint.group, constraint)

    dedicated_groups = [g for g, c in group_constraint.items() if c.mode == "dedicated"]
    other_exists = bool(pool) or any(c.mode != "dedicated" for c in group_constraint.values())

    # Clamp dedicated reservations in declaration order.
    reservations: dict[str, int] = {}
    clamped: list[str] = []
    budget = num_workers - (1 if other_exists else 0)
    for group in dedicated_groups:
        want = group_constraint[group].count
        got = max(1, min(want, budget))
        if got < want:
            clamped.append(f"{group}: {want} -> {got}")
        reservations[group] = got
        budget -= got
    if clamped and warn is not None:
        warn(
            "dedicated worker reservations exceed the pool and were clamped: " + "; ".join(clamped)
        )

    def shard_group(group_units, k, group, dedicated):
        bins = _lpt_shard_weighted(_unit_weights(group_units, durations), k)
        return [Batch(units=b, group=group, dedicated=dedicated) for b in bins]

    batches: list[Batch] = []
    for group in dedicated_groups:
        batches.extend(shard_group(grouped[group], reservations[group], group, True))
    for group, constraint in group_constraint.items():
        if constraint.mode == "dedicated":
            continue
        batches.extend(
            shard_group(grouped[group], min(constraint.count, num_workers), group, False)
        )
    if pool:
        pool_bins = max(1, num_workers - sum(reservations.values()))
        batches.extend(shard_group(pool, pool_bins, None, False))

    return ShardPlan(batches=batches, reservations=reservations)
