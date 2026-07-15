import unittest

from ctrlrunner.core.registry import TestItem
from ctrlrunner.core.selection import select_tests


def _item(id_, case_id=None, tags=None):
    return TestItem(
        id=id_, func=lambda: None, params=[], timeout=30, tags=tags or set(), case_id=case_id
    )


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tests = [
            _item("mod::a", case_id="TC-1", tags={"smoke"}),
            _item("mod::b", case_id="TC-2", tags={"regression"}),
            _item("mod::c[en]", case_id="TC-100-en", tags={"smoke", "i18n"}),
            _item("mod::c[uk]", case_id="TC-100-uk", tags={"smoke", "i18n"}),
        ]

    def test_no_filters_returns_everything(self):
        self.assertEqual(select_tests(self.tests), self.tests)

    def test_filter_by_exact_test_id(self):
        result = select_tests(self.tests, test_ids=["mod::a"])
        self.assertEqual([t.id for t in result], ["mod::a"])

    def test_filter_by_multiple_case_ids(self):
        result = select_tests(self.tests, case_ids=["TC-1", "TC-100-en"])
        self.assertEqual({t.case_id for t in result}, {"TC-1", "TC-100-en"})

    def test_filter_by_case_id_prefix_selects_all_parametrized_variants(self):
        result = select_tests(self.tests, case_id_prefixes=["TC-100"])
        self.assertEqual({t.case_id for t in result}, {"TC-100-en", "TC-100-uk"})

    def test_filter_by_tag(self):
        result = select_tests(self.tests, tags=["regression"])
        self.assertEqual([t.id for t in result], ["mod::b"])

    def test_filters_are_combined_with_and(self):
        result = select_tests(self.tests, tags=["smoke"], case_id_prefixes=["TC-100"])
        self.assertEqual({t.case_id for t in result}, {"TC-100-en", "TC-100-uk"})

    def test_no_match_returns_empty_list(self):
        result = select_tests(self.tests, case_ids=["does-not-exist"])
        self.assertEqual(result, [])

    def test_exclude_tags_drops_tests_with_any_excluded_tag(self):
        result = select_tests(self.tests, exclude_tags=["i18n"])
        self.assertEqual([t.id for t in result], ["mod::a", "mod::b"])

    def test_exclude_tags_combined_with_include_tags(self):
        # include smoke (a, c[en], c[uk]) then exclude i18n -> only a
        result = select_tests(self.tests, tags=["smoke"], exclude_tags=["i18n"])
        self.assertEqual([t.id for t in result], ["mod::a"])

    def test_exclude_tags_none_or_empty_is_a_no_op(self):
        self.assertEqual(select_tests(self.tests, exclude_tags=None), self.tests)
        self.assertEqual(select_tests(self.tests, exclude_tags=[]), self.tests)

    def test_grep_matches_against_test_id(self):
        result = select_tests(self.tests, grep=r"c\[")
        self.assertEqual({t.id for t in result}, {"mod::c[en]", "mod::c[uk]"})

    def test_grep_not_excludes_matching_ids(self):
        result = select_tests(self.tests, grep_not=r"c\[")
        self.assertEqual({t.id for t in result}, {"mod::a", "mod::b"})

    def test_grep_and_grep_not_combine_with_and(self):
        result = select_tests(self.tests, grep=r"^mod::", grep_not=r"en\]")
        self.assertEqual({t.id for t in result}, {"mod::a", "mod::b", "mod::c[uk]"})

    def test_grep_none_is_a_no_op(self):
        self.assertEqual(select_tests(self.tests, grep=None), self.tests)
        self.assertEqual(select_tests(self.tests, grep_not=None), self.tests)


if __name__ == "__main__":
    unittest.main()
