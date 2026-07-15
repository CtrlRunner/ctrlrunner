import unittest
from pathlib import Path
from unittest import mock

from ctrlrunner.core.registry import TestItem
from ctrlrunner.execution.worker_budget import (
    ExecUnit,
    WorkerConstraint,
    WorkerConstraintSpec,
    assign_worker_groups,
    build_units,
    group_aware_shard,
    load_worker_constraints,
    order_units,
    resolve_num_workers,
)


def _single(test_id):
    return ExecUnit(key=test_id, kind="single", test_ids=(test_id,))


def _file_unit(path, test_ids):
    return ExecUnit(key=f"file::{path}", kind="file", test_ids=tuple(test_ids))


def _item(
    test_id,
    path="tests/test_a.py",
    class_name=None,
    workers=None,
    workers_mode=None,
    serial_group=None,
    serial_retries=0,
    fully_parallel=None,
):
    return TestItem(
        id=test_id,
        func=lambda: None,
        params=[],
        source_path=Path(path),
        class_name=class_name,
        workers=workers,
        workers_mode=workers_mode,
        serial_group=serial_group,
        serial_retries=serial_retries,
        fully_parallel=fully_parallel,
    )


def _spec(path, class_name=None, count=1, mode="cap", order=0):
    return WorkerConstraintSpec(
        path_pattern=path, class_name=class_name, count=count, mode=mode, order=order
    )


class ResolveNumWorkersTests(unittest.TestCase):
    def test_auto_is_cpu_count_minus_one(self):
        with mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=8):
            self.assertEqual(resolve_num_workers("auto"), 7)

    def test_auto_never_drops_below_one(self):
        with mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=1):
            self.assertEqual(resolve_num_workers("auto"), 1)

    def test_none_means_auto(self):
        with mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=8):
            self.assertEqual(resolve_num_workers(None), 7)

    def test_percent_of_cpu_count(self):
        with mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=8):
            self.assertEqual(resolve_num_workers("50%"), 4)

    def test_percent_over_100_allows_oversubscription(self):
        with mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=8):
            self.assertEqual(resolve_num_workers("150%"), 12)

    def test_small_percent_floors_at_one(self):
        with mock.patch("ctrlrunner.execution.worker_budget._cpu_count", return_value=4):
            self.assertEqual(resolve_num_workers("10%"), 1)

    def test_positive_int_passes_through_unchanged(self):
        # idempotence: already-resolved values survive a second call, so
        # every layer (cli, projects, run_controller) can call this
        # defensively without tracking "already resolved".
        self.assertEqual(resolve_num_workers(6), 6)
        self.assertEqual(resolve_num_workers(1), 1)

    def test_zero_and_negative_ints_rejected(self):
        with self.assertRaises(ValueError):
            resolve_num_workers(0)
        with self.assertRaises(ValueError):
            resolve_num_workers(-1)

    def test_bool_rejected_despite_being_an_int_subclass(self):
        # TOML `true` arrives as a Python bool, which passes
        # isinstance(x, int) -- must be rejected explicitly.
        with self.assertRaises(ValueError):
            resolve_num_workers(True)
        with self.assertRaises(ValueError):
            resolve_num_workers(False)

    def test_arbitrary_string_rejected(self):
        with self.assertRaises(ValueError):
            resolve_num_workers("fast")

    def test_float_rejected(self):
        with self.assertRaises(ValueError):
            resolve_num_workers(2.5)

    def test_zero_percent_rejected(self):
        with self.assertRaises(ValueError):
            resolve_num_workers("0%")

    def test_negative_percent_rejected(self):
        with self.assertRaises(ValueError):
            resolve_num_workers("-5%")

    def test_percent_with_inner_space_rejected(self):
        with self.assertRaises(ValueError):
            resolve_num_workers("50 %")

    def test_error_message_names_the_bad_value(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_num_workers("banana")
        self.assertIn("banana", str(ctx.exception))


class LoadWorkerConstraintsTests(unittest.TestCase):
    def test_absent_workers_table_gives_empty_list(self):
        self.assertEqual(load_worker_constraints({}), [])
        self.assertEqual(load_worker_constraints({"num_workers": 4}), [])

    def test_plain_int_value_becomes_cap_spec(self):
        specs = load_worker_constraints({"workers": {"tests/test_a.py": 2}})
        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec.path_pattern, "tests/test_a.py")
        self.assertIsNone(spec.class_name)
        self.assertEqual(spec.count, 2)
        self.assertEqual(spec.mode, "cap")

    def test_inline_table_with_mode(self):
        specs = load_worker_constraints(
            {"workers": {"tests/test_a.py": {"count": 3, "mode": "dedicated"}}}
        )
        self.assertEqual(specs[0].count, 3)
        self.assertEqual(specs[0].mode, "dedicated")

    def test_class_qualified_key_splits_path_and_class(self):
        specs = load_worker_constraints({"workers": {"tests/test_a.py::LoginTests": 1}})
        self.assertEqual(specs[0].path_pattern, "tests/test_a.py")
        self.assertEqual(specs[0].class_name, "LoginTests")

    def test_declaration_order_is_preserved(self):
        specs = load_worker_constraints({"workers": {"b.py": 1, "a.py": 2, "c.py": 3}})
        self.assertEqual([s.order for s in specs], [0, 1, 2])
        self.assertEqual([s.path_pattern for s in specs], ["b.py", "a.py", "c.py"])

    def test_count_below_one_raises_naming_the_key(self):
        with self.assertRaises(ValueError) as ctx:
            load_worker_constraints({"workers": {"tests/test_a.py": 0}})
        self.assertIn("tests/test_a.py", str(ctx.exception))

    def test_bool_value_raises(self):
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": {"tests/test_a.py": True}})

    def test_auto_and_percent_rejected_for_group_counts(self):
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": {"tests/test_a.py": "auto"}})
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": {"tests/test_a.py": "50%"}})

    def test_table_without_count_raises(self):
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": {"tests/test_a.py": {"mode": "cap"}}})

    def test_unknown_table_key_raises(self):
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": {"tests/test_a.py": {"count": 2, "mod": "cap"}}})

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            load_worker_constraints(
                {"workers": {"tests/test_a.py": {"count": 2, "mode": "exclusive"}}}
            )

    def test_empty_path_raises(self):
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": {"": 2}})

    def test_empty_class_after_separator_raises(self):
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": {"tests/test_a.py::": 2}})

    def test_non_table_workers_value_raises(self):
        with self.assertRaises(ValueError):
            load_worker_constraints({"workers": 4})


class AssignWorkerGroupsTests(unittest.TestCase):
    def test_no_specs_and_no_decorator_gives_empty_mapping(self):
        tests = [_item("mod::test_a")]
        self.assertEqual(assign_worker_groups(tests, []), {})

    def test_exact_file_match(self):
        tests = [_item("mod::test_a", path="tests/test_a.py")]
        result = assign_worker_groups(tests, [_spec("tests/test_a.py", count=2)])
        constraint = result["mod::test_a"]
        self.assertEqual(constraint.count, 2)
        self.assertEqual(constraint.mode, "cap")
        self.assertEqual(constraint.group, "tests/test_a.py")

    def test_glob_match(self):
        tests = [_item("mod::test_a", path="tests/api/test_rate_limit.py")]
        result = assign_worker_groups(tests, [_spec("tests/api/test_rate_*.py", count=3)])
        self.assertEqual(result["mod::test_a"].count, 3)

    def test_unmatched_test_is_absent_from_mapping(self):
        tests = [_item("mod::test_a", path="tests/test_other.py")]
        result = assign_worker_groups(tests, [_spec("tests/test_a.py")])
        self.assertNotIn("mod::test_a", result)

    def test_class_qualified_spec_matches_only_that_class(self):
        tests = [
            _item("mod::Login.test_a", class_name="Login"),
            _item("mod::Other.test_b", class_name="Other"),
            _item("mod::test_plain"),
        ]
        result = assign_worker_groups(
            tests, [_spec("tests/test_a.py", class_name="Login", count=1)]
        )
        self.assertIn("mod::Login.test_a", result)
        self.assertNotIn("mod::Other.test_b", result)
        self.assertNotIn("mod::test_plain", result)

    def test_class_qualified_exact_beats_exact_file(self):
        tests = [_item("mod::Login.test_a", class_name="Login")]
        result = assign_worker_groups(
            tests,
            [
                _spec("tests/test_a.py", count=4, order=0),
                _spec("tests/test_a.py", class_name="Login", count=1, order=1),
            ],
        )
        self.assertEqual(result["mod::Login.test_a"].count, 1)

    def test_exact_file_beats_glob(self):
        tests = [_item("mod::test_a", path="tests/test_a.py")]
        result = assign_worker_groups(
            tests,
            [
                _spec("tests/test_*.py", count=4, order=0),
                _spec("tests/test_a.py", count=1, order=1),
            ],
        )
        self.assertEqual(result["mod::test_a"].count, 1)

    def test_class_qualified_glob_beats_exact_file(self):
        tests = [_item("mod::Login.test_a", class_name="Login")]
        result = assign_worker_groups(
            tests,
            [
                _spec("tests/test_a.py", count=4, order=0),
                _spec("tests/*.py", class_name="Login", count=1, order=1),
            ],
        )
        self.assertEqual(result["mod::Login.test_a"].count, 1)

    def test_specificity_tie_first_declared_wins(self):
        tests = [_item("mod::test_a", path="tests/test_a.py")]
        result = assign_worker_groups(
            tests,
            [
                _spec("tests/test_a*.py", count=2, order=0),
                _spec("tests/test_?.py", count=5, order=1),
            ],
        )
        self.assertEqual(result["mod::test_a"].count, 2)

    def test_config_beats_decorator(self):
        tests = [_item("mod::Login.test_a", class_name="Login", workers=5, workers_mode="cap")]
        result = assign_worker_groups(tests, [_spec("tests/test_a.py", count=1)])
        self.assertEqual(result["mod::Login.test_a"].count, 1)

    def test_decorator_fallback_when_no_config_matches(self):
        tests = [
            _item("mod::Login.test_a", class_name="Login", workers=2, workers_mode="dedicated")
        ]
        result = assign_worker_groups(tests, [])
        constraint = result["mod::Login.test_a"]
        self.assertEqual(constraint.count, 2)
        self.assertEqual(constraint.mode, "dedicated")
        self.assertEqual(constraint.group, "tests/test_a.py::Login")

    def test_all_tests_matching_one_spec_share_one_group(self):
        tests = [
            _item("a::test_1", path="tests/test_a.py"),
            _item("b::test_2", path="tests/test_b.py"),
        ]
        result = assign_worker_groups(tests, [_spec("tests/test_*.py", count=2)])
        self.assertEqual(result["a::test_1"].group, result["b::test_2"].group)

    def test_absolute_source_path_matches_relative_pattern_under_cwd(self):
        abs_path = str(Path.cwd() / "tests" / "test_a.py")
        tests = [_item("mod::test_a", path=abs_path)]
        result = assign_worker_groups(tests, [_spec("tests/test_a.py", count=2)])
        self.assertIn("mod::test_a", result)


class BuildUnitsTests(unittest.TestCase):
    def test_default_groups_by_file_in_definition_order(self):
        tests = [
            _item("a::test_1", path="tests/test_a.py"),
            _item("a::test_2", path="tests/test_a.py"),
            _item("b::test_3", path="tests/test_b.py"),
        ]
        units, _ = build_units(tests, {}, fully_parallel_default=False)
        self.assertEqual(len(units), 2)
        file_a = next(u for u in units if "test_a" in u.key)
        self.assertEqual(file_a.kind, "file")
        self.assertEqual(file_a.test_ids, ("a::test_1", "a::test_2"))
        file_b = next(u for u in units if "test_b" in u.key)
        self.assertEqual(file_b.test_ids, ("b::test_3",))

    def test_fully_parallel_default_gives_one_unit_per_test(self):
        tests = [
            _item("a::test_1", path="tests/test_a.py"),
            _item("a::test_2", path="tests/test_a.py"),
        ]
        units, _ = build_units(tests, {}, fully_parallel_default=True)
        self.assertEqual(len(units), 2)
        for unit in units:
            self.assertEqual(unit.kind, "single")
            self.assertEqual(len(unit.test_ids), 1)

    def test_class_level_fully_parallel_overrides_grouped_default(self):
        tests = [
            _item("a::Par.test_1", path="tests/test_a.py", class_name="Par", fully_parallel=True),
            _item("a::Par.test_2", path="tests/test_a.py", class_name="Par", fully_parallel=True),
            _item("a::test_3", path="tests/test_a.py"),
        ]
        units, _ = build_units(tests, {}, fully_parallel_default=False)
        singles = [u for u in units if u.kind == "single"]
        files = [u for u in units if u.kind == "file"]
        self.assertEqual(len(singles), 2)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].test_ids, ("a::test_3",))

    def test_class_level_fully_parallel_false_overrides_parallel_default(self):
        tests = [
            _item(
                "a::Grouped.test_1",
                path="tests/test_a.py",
                class_name="Grouped",
                fully_parallel=False,
            ),
            _item("a::test_2", path="tests/test_a.py"),
        ]
        units, _ = build_units(tests, {}, fully_parallel_default=True)
        kinds = sorted(u.kind for u in units)
        self.assertEqual(kinds, ["file", "single"])
        file_unit = next(u for u in units if u.kind == "file")
        self.assertEqual(file_unit.test_ids, ("a::Grouped.test_1",))

    def test_serial_class_is_extracted_into_its_own_unit(self):
        tests = [
            _item("a::test_1", path="tests/test_a.py"),
            _item(
                "a::Flow.test_2",
                path="tests/test_a.py",
                class_name="Flow",
                serial_group="a::Flow",
                serial_retries=2,
            ),
            _item(
                "a::Flow.test_3",
                path="tests/test_a.py",
                class_name="Flow",
                serial_group="a::Flow",
                serial_retries=2,
            ),
            _item("a::test_4", path="tests/test_a.py"),
        ]
        units, _ = build_units(tests, {}, fully_parallel_default=False)
        serial = next(u for u in units if u.kind == "serial")
        self.assertEqual(serial.key, "a::Flow")
        self.assertEqual(serial.test_ids, ("a::Flow.test_2", "a::Flow.test_3"))
        self.assertEqual(serial.serial_retries, 2)
        file_unit = next(u for u in units if u.kind == "file")
        self.assertEqual(file_unit.test_ids, ("a::test_1", "a::test_4"))

    def test_serial_wins_even_under_fully_parallel_default(self):
        tests = [
            _item("a::Flow.test_1", class_name="Flow", serial_group="a::Flow"),
            _item("a::Flow.test_2", class_name="Flow", serial_group="a::Flow"),
        ]
        units, _ = build_units(tests, {}, fully_parallel_default=True)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].kind, "serial")

    def test_constraint_boundary_splits_a_file_unit(self):
        # a class-qualified constraint pulls that class's tests out of
        # the file's pool unit into its own constrained unit
        from ctrlrunner.execution.worker_budget import WorkerConstraint

        constraint = WorkerConstraint(group="tests/test_a.py::Login", count=1)
        tests = [
            _item("a::test_1", path="tests/test_a.py"),
            _item("a::Login.test_2", path="tests/test_a.py", class_name="Login"),
            _item("a::test_3", path="tests/test_a.py"),
        ]
        constraints_by_id = {"a::Login.test_2": constraint}
        units, cbu = build_units(tests, constraints_by_id, fully_parallel_default=False)
        self.assertEqual(len(units), 2)
        constrained = next(u for u in units if cbu.get(u.key) is not None)
        self.assertEqual(constrained.test_ids, ("a::Login.test_2",))
        self.assertEqual(cbu[constrained.key], constraint)
        pool = next(u for u in units if cbu.get(u.key) is None)
        self.assertEqual(pool.test_ids, ("a::test_1", "a::test_3"))

    def test_constraints_by_unit_maps_serial_and_single_units_too(self):
        from ctrlrunner.execution.worker_budget import WorkerConstraint

        constraint = WorkerConstraint(group="tests/test_a.py", count=2)
        tests = [
            _item("a::test_1", path="tests/test_a.py", fully_parallel=True),
            _item(
                "a::Flow.test_2",
                path="tests/test_a.py",
                class_name="Flow",
                serial_group="a::Flow",
            ),
        ]
        constraints_by_id = {
            "a::test_1": constraint,
            "a::Flow.test_2": constraint,
        }
        units, cbu = build_units(tests, constraints_by_id, fully_parallel_default=False)
        for unit in units:
            self.assertEqual(cbu[unit.key], constraint)

    def test_parametrized_variants_stay_contiguous_in_file_unit(self):
        tests = [
            _item("a::test_x[en]", path="tests/test_a.py"),
            _item("a::test_x[de]", path="tests/test_a.py"),
            _item("a::test_y", path="tests/test_a.py"),
        ]
        units, _ = build_units(tests, {}, fully_parallel_default=False)
        self.assertEqual(units[0].test_ids, ("a::test_x[en]", "a::test_x[de]", "a::test_y"))


class GroupAwareShardTests(unittest.TestCase):
    def test_singleton_units_no_constraints_no_history_match_chunk_exactly(self):
        # the fully_parallel degeneration guarantee: byte-identical
        # batches to today's round-robin _chunk()
        from ctrlrunner.execution.orchestrator import _chunk

        test_ids = [f"mod::test_{i}" for i in range(10)]
        units = [_single(tid) for tid in test_ids]
        for n in (1, 2, 3, 4, 7):
            plan = group_aware_shard(units, {}, n)
            flattened = [batch.test_ids for batch in plan.batches]
            self.assertEqual(flattened, _chunk(test_ids, min(n, len(test_ids))))

    def test_file_units_never_split_and_batch_count_capped(self):
        units = [
            _file_unit("a.py", ["a::1", "a::2", "a::3"]),
            _file_unit("b.py", ["b::1", "b::2"]),
            _file_unit("c.py", ["c::1"]),
        ]
        plan = group_aware_shard(units, {}, 2)
        self.assertLessEqual(len(plan.batches), 2)
        # every file's tests stay contiguous inside one batch
        for unit in units:
            containing = [b for b in plan.batches if set(unit.test_ids) <= set(b.test_ids)]
            self.assertEqual(len(containing), 1, f"unit {unit.key} split across batches")

    def test_cap_group_shards_into_at_most_count_batches(self):
        constraint = WorkerConstraint(group="g", count=2)
        units = [_single(f"g::{i}") for i in range(5)]
        cbu = {u.key: constraint for u in units}
        plan = group_aware_shard(units, cbu, 8)
        self.assertEqual(len(plan.batches), 2)
        for batch in plan.batches:
            self.assertEqual(batch.group, "g")
            self.assertFalse(batch.dedicated)

    def test_cap_of_one_serializes_the_group_into_one_batch(self):
        constraint = WorkerConstraint(group="g", count=1)
        units = [_single(f"g::{i}") for i in range(4)]
        cbu = {u.key: constraint for u in units}
        plan = group_aware_shard(units, cbu, 8)
        self.assertEqual(len(plan.batches), 1)
        self.assertEqual(len(plan.batches[0].test_ids), 4)

    def test_cap_count_clamped_to_pool_size_silently(self):
        constraint = WorkerConstraint(group="g", count=10)
        units = [_single(f"g::{i}") for i in range(6)]
        cbu = {u.key: constraint for u in units}
        warnings: list[str] = []
        plan = group_aware_shard(units, cbu, 2, warn=warnings.append)
        self.assertLessEqual(len(plan.batches), 2)
        self.assertEqual(warnings, [])

    def test_dedicated_group_gets_reservation_and_labeled_batches(self):
        constraint = WorkerConstraint(group="d", count=2, mode="dedicated")
        units = [_single(f"d::{i}") for i in range(4)] + [_single("pool::1")]
        cbu = {u.key: constraint for u in units if u.key.startswith("d")}
        plan = group_aware_shard(units, cbu, 8)
        self.assertEqual(plan.reservations, {"d": 2})
        dedicated = [b for b in plan.batches if b.dedicated]
        self.assertEqual(len(dedicated), 2)
        for batch in dedicated:
            self.assertEqual(batch.group, "d")

    def test_pool_batch_count_shrinks_by_reservations(self):
        constraint = WorkerConstraint(group="d", count=3, mode="dedicated")
        units = [_single("d::1")] + [_single(f"pool::{i}") for i in range(20)]
        cbu = {"d::1": constraint}
        plan = group_aware_shard(units, cbu, 8)
        pool_batches = [b for b in plan.batches if b.group is None]
        # 8 - 3 reserved = 5 pool bins
        self.assertEqual(len(pool_batches), 5)

    def test_dedicated_reservations_clamped_with_warning(self):
        c1 = WorkerConstraint(group="d1", count=3, mode="dedicated")
        c2 = WorkerConstraint(group="d2", count=3, mode="dedicated")
        units = [_single("d1::1"), _single("d2::1"), _single("pool::1")]
        cbu = {"d1::1": c1, "d2::1": c2}
        warnings: list[str] = []
        plan = group_aware_shard(units, cbu, 4, warn=warnings.append)
        # budget = 4 - 1 (pool present) = 3: d1 keeps 3? no -- then d2
        # would get 0; each is floored at 1: d1 -> min(3, 3) = 3,
        # d2 -> max(1, min(3, 0)) = 1, and a warning is emitted
        self.assertEqual(plan.reservations["d1"], 3)
        self.assertEqual(plan.reservations["d2"], 1)
        self.assertEqual(len(warnings), 1)

    def test_batches_ordered_dedicated_then_cap_then_pool(self):
        ded = WorkerConstraint(group="d", count=1, mode="dedicated")
        cap = WorkerConstraint(group="c", count=1)
        units = [_single("pool::1"), _single("c::1"), _single("d::1")]
        cbu = {"c::1": cap, "d::1": ded}
        plan = group_aware_shard(units, cbu, 4)
        kinds = [
            "dedicated" if b.dedicated else ("cap" if b.group else "pool") for b in plan.batches
        ]
        self.assertEqual(kinds, ["dedicated", "cap", "pool"])

    def test_unit_weight_is_sum_of_member_durations(self):
        # one heavy file (two 10s tests) + two light files must not put
        # both light files with the heavy one when 2 bins are available
        heavy = _file_unit("heavy.py", ["h::1", "h::2"])
        light_a = _file_unit("la.py", ["la::1"])
        light_b = _file_unit("lb.py", ["lb::1"])
        durations = {"h::1": 10.0, "h::2": 10.0, "la::1": 1.0, "lb::1": 1.0}
        plan = group_aware_shard([heavy, light_a, light_b], {}, 2, durations=durations)
        heavy_batch = next(b for b in plan.batches if "h::1" in b.test_ids)
        self.assertEqual(heavy_batch.test_ids, ["h::1", "h::2"])

    def test_empty_units_give_empty_plan(self):
        plan = group_aware_shard([], {}, 4)
        self.assertEqual(plan.batches, [])
        self.assertEqual(plan.reservations, {})


class OrderUnitsTests(unittest.TestCase):
    def _units(self):
        return [
            ExecUnit(key="file::tests/test_c.py", kind="file", test_ids=("m::c",)),
            ExecUnit(key="file::tests/test_a.py", kind="file", test_ids=("m::a",)),
            ExecUnit(key="file::tests/test_b.py", kind="file", test_ids=("m::b",)),
        ]

    def test_declared_order_is_a_no_op(self):
        units = self._units()
        result = order_units(units, "declared", seed=None)
        self.assertEqual([u.key for u in result], [u.key for u in units])
        self.assertIs(result, units)

    def test_alpha_order_sorts_by_unit_key(self):
        result = order_units(self._units(), "alpha", seed=None)
        self.assertEqual(
            [u.key for u in result],
            ["file::tests/test_a.py", "file::tests/test_b.py", "file::tests/test_c.py"],
        )

    def test_random_order_is_deterministic_for_a_given_seed(self):
        result_1 = order_units(self._units(), "random", seed=42)
        result_2 = order_units(self._units(), "random", seed=42)
        self.assertEqual([u.key for u in result_1], [u.key for u in result_2])

    def test_random_order_differs_across_seeds_with_enough_units(self):
        # Uses more units than _units() (3! = 6 permutations is small
        # enough that two arbitrary seeds can genuinely collide -- e.g.
        # random.Random(1) and random.Random(2) both shuffle a 3-item
        # list to the same order). 8! = 40320 makes that collision
        # negligible, so a mismatch here means the seed is being
        # ignored, not bad luck.
        units = [
            ExecUnit(key=f"file::tests/test_{i}.py", kind="file", test_ids=(f"m::{i}",))
            for i in range(8)
        ]
        result_a = order_units(units, "random", seed=1)
        result_b = order_units(units, "random", seed=2)
        self.assertNotEqual([u.key for u in result_a], [u.key for u in result_b])

    def test_random_order_requires_an_int_seed(self):
        with self.assertRaises(ValueError):
            order_units(self._units(), "random", seed=None)

    def test_unknown_order_raises(self):
        with self.assertRaises(ValueError):
            order_units(self._units(), "banana", seed=None)


if __name__ == "__main__":
    unittest.main()
