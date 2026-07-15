import json
import unittest

from ctrlrunner.core.registry import TestItem
from ctrlrunner.reporting.list_output import ALL_FIELDS, DEFAULT_FIELDS, format_list


def _item(
    id_, case_id=None, tags=None, timeout=None, retries=None, class_name=None, properties=None
):
    return TestItem(
        id=id_,
        func=lambda: None,
        params=[],
        case_id=case_id,
        tags=set(tags or []),
        timeout=timeout,
        retries=retries,
        class_name=class_name,
        properties=properties or {},
    )


class FormatListTests(unittest.TestCase):
    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            format_list([], "yaml")

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            format_list([], "text", fields=["not_a_real_field"])

    def test_json_includes_every_field_regardless_of_list_fields(self):
        items = [
            _item(
                "mod::test_a",
                case_id="TC-1",
                tags=["smoke"],
                timeout=30,
                retries=2,
                class_name="Suite",
                properties={"owner": "team_a"},
            )
        ]
        out = format_list(items, "json", fields=["id"])  # fields arg ignored for json
        data = json.loads(out)
        row = data["tests"][0]
        self.assertEqual(row["id"], "mod::test_a")
        self.assertEqual(row["caseId"], "TC-1")
        self.assertEqual(row["tags"], ["smoke"])
        self.assertEqual(row["timeout"], 30)
        self.assertEqual(row["retries"], 2)
        self.assertEqual(row["className"], "Suite")
        self.assertEqual(row["properties"], {"owner": "team_a"})

    def test_json_empty_list_is_valid_json(self):
        out = format_list([], "json")
        self.assertEqual(json.loads(out), {"tests": []})

    def test_text_default_fields_one_line_per_test(self):
        items = [_item("mod::test_a", case_id="TC-1", tags=["smoke", "regression"])]
        out = format_list(items, "text")
        self.assertEqual(len(out.splitlines()), 1)
        line = out.splitlines()[0]
        self.assertIn("mod::test_a", line)
        self.assertIn("caseId=TC-1", line)
        self.assertIn("tags=regression,smoke", line)

    def test_text_respects_custom_fields_selection(self):
        items = [_item("mod::test_a", timeout=15, retries=1)]
        out = format_list(items, "text", fields=["id", "timeout", "retries"])
        line = out.splitlines()[0]
        self.assertIn("mod::test_a", line)
        self.assertIn("timeout=15", line)
        self.assertIn("retries=1", line)
        self.assertNotIn("caseId", line)  # not requested

    def test_text_omits_empty_fields_cleanly(self):
        items = [_item("mod::test_a")]  # no case_id, no tags
        out = format_list(items, "text")
        line = out.splitlines()[0]
        self.assertEqual(line, "mod::test_a")

    def test_text_multiple_tests_multiple_lines(self):
        items = [_item("mod::a"), _item("mod::b"), _item("mod::c")]
        out = format_list(items, "text")
        self.assertEqual(len(out.splitlines()), 3)

    def test_md_produces_a_valid_looking_table(self):
        items = [_item("mod::test_a", case_id="TC-1", tags=["smoke"])]
        out = format_list(items, "md")
        lines = out.splitlines()
        self.assertEqual(len(lines), 3)  # header, separator, one row
        self.assertTrue(lines[0].startswith("| id |"))
        self.assertTrue(lines[1].startswith("| ---"))
        self.assertIn("mod::test_a", lines[2])
        self.assertIn("TC-1", lines[2])
        self.assertIn("smoke", lines[2])

    def test_md_respects_custom_field_order(self):
        items = [_item("mod::test_a", timeout=10)]
        out = format_list(items, "md", fields=["timeout", "id"])
        header = out.splitlines()[0]
        self.assertEqual(header, "| timeout | id |")

    def test_default_fields_constant_matches_documented_default(self):
        self.assertEqual(DEFAULT_FIELDS, ["id", "caseId", "tags"])

    def test_all_fields_constant_is_a_superset_of_default(self):
        self.assertTrue(set(DEFAULT_FIELDS).issubset(set(ALL_FIELDS)))

    def test_project_field_is_supported(self):
        item = _item("mod::test_a")
        item.project = "smoke"
        out = format_list([item], "json")
        data = json.loads(out)
        self.assertEqual(data["tests"][0]["project"], "smoke")

    def test_project_field_defaults_to_none(self):
        item = _item("mod::test_a")
        out = format_list([item], "json")
        data = json.loads(out)
        self.assertIsNone(data["tests"][0]["project"])

    def test_risk_flag_field_is_supported(self):
        item = _item("mod::test_a")
        item.risk_flag = True
        out = format_list([item], "json")
        data = json.loads(out)
        self.assertTrue(data["tests"][0]["riskFlag"])

    def test_risk_flag_defaults_to_false(self):
        item = _item("mod::test_a")
        out = format_list([item], "json")
        data = json.loads(out)
        self.assertFalse(data["tests"][0]["riskFlag"])


if __name__ == "__main__":
    unittest.main()
