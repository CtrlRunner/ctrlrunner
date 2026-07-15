import unittest
from pathlib import Path

from ctrlrunner.core.registry import TestItem
from ctrlrunner.reporting.grouping import (
    DEFAULT_DIMENSIONS,
    UNGROUPED,
    GroupingDimension,
    compute_groups,
    load_grouping_dimensions,
)


def _item(id_="mod::test_x", source_path=None, tags=None, properties=None):
    return TestItem(
        id=id_,
        func=lambda: None,
        params=[],
        source_path=Path(source_path) if source_path else None,
        tags=set(tags or []),
        properties=properties or {},
    )


class LoadGroupingDimensionsTests(unittest.TestCase):
    def test_absent_config_returns_default_module_dimension(self):
        dims = load_grouping_dimensions({})
        self.assertEqual(dims, DEFAULT_DIMENSIONS)

    def test_custom_dimensions_force_include_module_when_omitted(self):
        # Module must always be present -- every existing consumer
        # (the default HTML report view, historical grouping behavior)
        # relies on it, so a user adding a custom dimension without
        # re-listing "module" must not silently lose it.
        dims = load_grouping_dimensions(
            {
                "grouping": {
                    "dimensions": [{"name": "team", "strategy": "tag_prefix", "prefix": "team_"}]
                }
            }
        )
        names = [d.name for d in dims]
        self.assertEqual(names, ["module", "team"])  # "module" auto-added, prepended

    def test_module_not_duplicated_when_already_listed(self):
        dims = load_grouping_dimensions(
            {
                "grouping": {
                    "dimensions": [
                        {"name": "team", "strategy": "tag_prefix", "prefix": "team_"},
                        {"name": "module", "strategy": "module"},
                    ]
                }
            }
        )
        names = [d.name for d in dims]
        self.assertEqual(names, ["team", "module"])  # order preserved, no duplicate prepended

    def test_explicit_empty_dimensions_still_raises(self):
        # The deliberate exception: an explicit empty list is user intent
        # gone wrong and must still fail fast, not be "fixed" by
        # auto-adding module.
        with self.assertRaises(ValueError):
            load_grouping_dimensions({"grouping": {"dimensions": []}})

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            load_grouping_dimensions(
                {"grouping": {"dimensions": [{"name": "x", "strategy": "not_a_real_strategy"}]}}
            )

    def test_missing_name_or_strategy_raises(self):
        with self.assertRaises(ValueError):
            load_grouping_dimensions({"grouping": {"dimensions": [{"strategy": "module"}]}})
        with self.assertRaises(ValueError):
            load_grouping_dimensions({"grouping": {"dimensions": [{"name": "x"}]}})

    def test_path_strategy_missing_depth_raises(self):
        with self.assertRaises(ValueError):
            load_grouping_dimensions(
                {"grouping": {"dimensions": [{"name": "suite", "strategy": "path"}]}}
            )

    def test_path_strategy_non_int_depth_raises_clearly(self):
        # Depth was presence-checked but not type-checked -- a
        # TOML author writing `depth = "2"` (a string, not an int) would
        # previously sail through here and fail confusingly later inside
        # _group_by_path's min/max arithmetic instead of at config load.
        with self.assertRaises(ValueError):
            load_grouping_dimensions(
                {"grouping": {"dimensions": [{"name": "suite", "strategy": "path", "depth": "2"}]}}
            )

    def test_path_strategy_bool_depth_raises(self):
        # bool is technically an int subclass in Python -- explicitly
        # reject it too, since `depth = true` is never sensible.
        with self.assertRaises(ValueError):
            load_grouping_dimensions(
                {"grouping": {"dimensions": [{"name": "suite", "strategy": "path", "depth": True}]}}
            )

    def test_tag_prefix_strategy_missing_prefix_raises(self):
        with self.assertRaises(ValueError):
            load_grouping_dimensions(
                {"grouping": {"dimensions": [{"name": "team", "strategy": "tag_prefix"}]}}
            )

    def test_property_strategy_missing_key_raises(self):
        with self.assertRaises(ValueError):
            load_grouping_dimensions(
                {"grouping": {"dimensions": [{"name": "owner", "strategy": "property"}]}}
            )

    def test_empty_dimensions_list_raises(self):
        with self.assertRaises(ValueError):
            load_grouping_dimensions({"grouping": {"dimensions": []}})

    def test_empty_grouping_table_raises_same_as_explicit_empty_dimensions(self):
        # A bare [ctrlrunner.grouping] header with no keys at all
        # is falsy and today silently returns the module default -- but
        # an explicit `dimensions = []` already (correctly) raises.
        # Both are "the user configured grouping and got nothing usable"
        # and must fail the same way.
        with self.assertRaises(ValueError):
            load_grouping_dimensions({"grouping": {}})

    def test_valid_multi_dimension_config_parses(self):
        dims = load_grouping_dimensions(
            {
                "grouping": {
                    "dimensions": [
                        {"name": "module", "strategy": "module"},
                        {"name": "suite", "strategy": "path", "depth": 1},
                        {"name": "team", "strategy": "tag_prefix", "prefix": "team_"},
                        {"name": "owner", "strategy": "property", "key": "owner"},
                    ]
                }
            }
        )
        self.assertEqual(len(dims), 4)
        self.assertEqual(dims[1].options["depth"], 1)


class ComputeGroupsTests(unittest.TestCase):
    def test_module_strategy_matches_old_hardcoded_split(self):
        item = _item(id_="pkg.mod::test_x[chromium]")
        groups = compute_groups(item, [GroupingDimension(name="module", strategy="module")])
        self.assertEqual(groups, {"module": "pkg.mod"})

    def test_path_strategy_worked_example_from_the_plan(self):
        # the plan's own motivating example: tests/web/cases/... -> "cases"
        # with root "tests" and depth=1; depth=0 -> "web".
        item = _item(source_path="/project/tests/web/cases/test_login.py")
        dims_depth0 = [GroupingDimension(name="suite", strategy="path", options={"depth": 0})]
        dims_depth1 = [GroupingDimension(name="suite", strategy="path", options={"depth": 1})]
        self.assertEqual(compute_groups(item, dims_depth0, root="/project/tests"), {"suite": "web"})
        self.assertEqual(
            compute_groups(item, dims_depth1, root="/project/tests"), {"suite": "cases"}
        )

    def test_path_strategy_depth_beyond_actual_depth_falls_back_to_last_segment(self):
        item = _item(source_path="/project/tests/web/test_login.py")
        dims = [GroupingDimension(name="suite", strategy="path", options={"depth": 5})]
        self.assertEqual(compute_groups(item, dims, root="/project/tests"), {"suite": "web"})

    def test_path_strategy_file_directly_in_root_is_ungrouped(self):
        item = _item(source_path="/project/tests/test_login.py")
        dims = [GroupingDimension(name="suite", strategy="path", options={"depth": 0})]
        self.assertEqual(compute_groups(item, dims, root="/project/tests"), {"suite": UNGROUPED})

    def test_path_strategy_no_source_path_is_ungrouped(self):
        item = _item(source_path=None)
        dims = [GroupingDimension(name="suite", strategy="path", options={"depth": 0})]
        self.assertEqual(compute_groups(item, dims, root="/project/tests"), {"suite": UNGROUPED})

    def test_tag_prefix_strategy_strips_prefix(self):
        item = _item(tags=["team_backend", "smoke"])
        dims = [GroupingDimension(name="team", strategy="tag_prefix", options={"prefix": "team_"})]
        self.assertEqual(compute_groups(item, dims), {"team": "backend"})

    def test_tag_prefix_strategy_no_match_is_ungrouped(self):
        item = _item(tags=["smoke"])
        dims = [GroupingDimension(name="team", strategy="tag_prefix", options={"prefix": "team_"})]
        self.assertEqual(compute_groups(item, dims), {"team": UNGROUPED})

    def test_tag_prefix_strategy_multiple_matches_joined_deterministically(self):
        item = _item(tags=["team_b", "team_a"])
        dims = [GroupingDimension(name="team", strategy="tag_prefix", options={"prefix": "team_"})]
        self.assertEqual(compute_groups(item, dims), {"team": "a+b"})  # sorted, not insertion order

    def test_property_strategy_reads_the_key(self):
        item = _item(properties={"owner": "team_checkout"})
        dims = [GroupingDimension(name="owner", strategy="property", options={"key": "owner"})]
        self.assertEqual(compute_groups(item, dims), {"owner": "team_checkout"})

    def test_property_strategy_missing_key_is_ungrouped(self):
        item = _item(properties={})
        dims = [GroupingDimension(name="owner", strategy="property", options={"key": "owner"})]
        self.assertEqual(compute_groups(item, dims), {"owner": UNGROUPED})

    def test_multiple_dimensions_computed_independently(self):
        item = _item(
            id_="pkg.mod::test_x",
            tags=["team_backend"],
            source_path="/project/tests/web/test_x.py",
            properties={"owner": "alice"},
        )
        dims = [
            GroupingDimension(name="module", strategy="module"),
            GroupingDimension(name="suite", strategy="path", options={"depth": 0}),
            GroupingDimension(name="team", strategy="tag_prefix", options={"prefix": "team_"}),
            GroupingDimension(name="owner", strategy="property", options={"key": "owner"}),
        ]
        groups = compute_groups(item, dims, root="/project/tests")
        self.assertEqual(
            groups,
            {
                "module": "pkg.mod",
                "suite": "web",
                "team": "backend",
                "owner": "alice",
            },
        )


if __name__ == "__main__":
    unittest.main()
