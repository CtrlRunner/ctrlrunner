import unittest

from ctrlrunner.core.registry import TestItem
from ctrlrunner.reporting.collection_summary import format_collection_summary


def _item(id_, tags=None):
    return TestItem(id=id_, func=lambda: None, params=[], tags=tags or set())


class FormatCollectionSummaryTests(unittest.TestCase):
    def test_single_test_single_file(self):
        summary = format_collection_summary([_item("mod::test_a")])
        self.assertEqual(summary, "Collected 1 test across 1 file")

    def test_plural_counts(self):
        tests = [_item("mod_a::test_1"), _item("mod_a::test_2"), _item("mod_b::test_1")]
        summary = format_collection_summary(tests)
        self.assertEqual(summary, "Collected 3 tests across 2 files")

    def test_tag_counts_included_when_present(self):
        tests = [
            _item("mod::test_1", tags={"smoke"}),
            _item("mod::test_2", tags={"smoke"}),
            _item("mod::test_3", tags={"regression"}),
        ]
        summary = format_collection_summary(tests)
        self.assertIn("2 tagged smoke", summary)
        self.assertIn("1 tagged regression", summary)

    def test_no_tags_omits_tag_breakdown(self):
        summary = format_collection_summary([_item("mod::test_a")])
        self.assertNotIn("tagged", summary)

    def test_empty_list(self):
        summary = format_collection_summary([])
        self.assertEqual(summary, "Collected 0 tests across 0 files")


if __name__ == "__main__":
    unittest.main()
