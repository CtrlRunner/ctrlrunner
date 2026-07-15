import unittest

from ctrlrunner.config.tag_registry import (
    TagRegistry,
    format_unregistered_tags_warning,
    load_tag_registry,
    validate_tags,
    warn_unregistered_cli_tags,
)
from ctrlrunner.core.registry import TestItem


def _item(tags):
    return TestItem(id="mod::test_x", func=lambda: None, params=[], tags=set(tags))


class TagRegistryTests(unittest.TestCase):
    def test_exact_match(self):
        reg = TagRegistry(entries=["smoke", "regression"])
        self.assertTrue(reg.is_registered("smoke"))
        self.assertFalse(reg.is_registered("hotfix"))

    def test_prefix_pattern_match(self):
        reg = TagRegistry(entries=["team:*"])
        self.assertTrue(reg.is_registered("team:backend"))
        self.assertTrue(reg.is_registered("team:"))
        self.assertFalse(reg.is_registered("teamx"))
        self.assertFalse(reg.is_registered("other"))

    def test_underscore_prefix_pattern_is_literal_not_special(self):
        # only a trailing "*" makes an entry a prefix pattern; "team_*"
        # is itself just such an entry (the "_" has no special meaning).
        reg = TagRegistry(entries=["team_*"])
        self.assertTrue(reg.is_registered("team_backend"))
        self.assertFalse(reg.is_registered("teamXbackend"))

    def test_arbitrary_trailing_star_is_not_treated_as_a_prefix_pattern(self):
        # Only the documented ":*"/"_*" suffix forms are prefix
        # patterns -- an entry like "footer*" (a bare letter directly
        # before the "*", no ":"/"_") used to silently match ANY tag
        # starting with "footer", far more than the documented syntax
        # promises. It should now be treated as a literal (and
        # therefore practically un-matchable) entry instead.
        reg = TagRegistry(entries=["footer*"])
        self.assertFalse(reg.is_registered("footer_anything"))
        self.assertFalse(reg.is_registered("footerish"))

    def test_bare_wildcard_entry_matches_nothing_even_if_constructed_directly(self):
        # load_tag_registry() already rejects a bare "*" up front; this
        # guards TagRegistry itself (e.g. constructed directly by a
        # test or another caller) against the same footgun -- a bare
        # "*" must never silently disable validation entirely.
        reg = TagRegistry(entries=["*"])
        self.assertFalse(reg.is_registered("anything"))
        self.assertFalse(reg.is_registered(""))

    def test_unregistered_returns_only_unmatched_tags(self):
        reg = TagRegistry(entries=["smoke", "team:*"])
        result = reg.unregistered({"smoke", "team:backend", "hotfix", "wip"})
        self.assertEqual(result, {"hotfix", "wip"})

    def test_unregistered_empty_when_all_match(self):
        reg = TagRegistry(entries=["smoke"])
        self.assertEqual(reg.unregistered({"smoke"}), set())


class LoadTagRegistryTests(unittest.TestCase):
    def test_present_key_builds_registry_defaulting_non_strict(self):
        reg = load_tag_registry({"registered_tags": ["smoke"]})
        self.assertIsNotNone(reg)
        self.assertEqual(reg.entries, ["smoke"])
        self.assertFalse(reg.strict)

    def test_strict_tags_config_is_read(self):
        reg = load_tag_registry({"registered_tags": ["smoke"], "strict_tags": True})
        self.assertTrue(reg.strict)

    def test_strict_override_wins_over_config(self):
        reg = load_tag_registry(
            {"registered_tags": ["smoke"], "strict_tags": False}, strict_override=True
        )
        self.assertTrue(reg.strict)

    def test_strict_override_none_falls_back_to_config(self):
        reg = load_tag_registry(
            {"registered_tags": ["smoke"], "strict_tags": True}, strict_override=None
        )
        self.assertTrue(reg.strict)

    def test_bare_wildcard_entry_raises_value_error(self):
        # A bare "*" entry silently matches every tag, defeating
        # the registry's entire purpose -- fail fast instead.
        with self.assertRaises(ValueError):
            load_tag_registry({"registered_tags": ["smoke", "*"]})


class ValidateTagsTests(unittest.TestCase):
    def test_no_unregistered_tags_returns_empty_list(self):
        reg = TagRegistry(entries=["smoke"])
        tests = [_item({"smoke"}), _item({"smoke"})]
        self.assertEqual(validate_tags(tests, reg), [])

    def test_finds_unregistered_tags_across_all_tests_sorted(self):
        reg = TagRegistry(entries=["smoke"])
        tests = [_item({"smoke", "wip"}), _item({"hotfix"})]
        self.assertEqual(validate_tags(tests, reg), ["hotfix", "wip"])

    def test_validates_against_every_test_not_just_a_selected_subset(self):
        # the whole point: a typo on a test nobody's currently filtering
        # for must still be caught, since validation runs at discovery
        # time, before selection.
        reg = TagRegistry(entries=["smoke"])
        tests = [_item({"smoke"}), _item({"typo_tag"})]
        self.assertEqual(validate_tags(tests, reg), ["typo_tag"])


class WarnUnregisteredCliTagsTests(unittest.TestCase):
    def test_no_registry_prints_nothing(self):
        # must not raise / must not require a registry to exist
        warn_unregistered_cli_tags(["anything"], None)

    def test_prints_warning_for_unregistered_cli_tag(self):
        import contextlib
        import io

        reg = TagRegistry(entries=["smoke"])
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            warn_unregistered_cli_tags(["hotfix-123"], reg)
        self.assertIn("hotfix-123", buf.getvalue())

    def test_strict_registry_still_only_warns_never_raises(self):
        # this check is ALWAYS warning-only, even in strict mode --
        # blocking ad hoc --tag filtering would make it unusable.
        import contextlib
        import io

        reg = TagRegistry(entries=["smoke"], strict=True)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            warn_unregistered_cli_tags(["hotfix-123"], reg)  # must not raise
        self.assertIn("hotfix-123", buf.getvalue())

    def test_registered_cli_tag_prints_nothing(self):
        import contextlib
        import io

        reg = TagRegistry(entries=["smoke"])
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            warn_unregistered_cli_tags(["smoke"], reg)
        self.assertEqual(buf.getvalue(), "")


class FormatUnregisteredTagsWarningTests(unittest.TestCase):
    def test_message_includes_count_and_sorted_tags(self):
        msg = format_unregistered_tags_warning(["wip", "hotfix"])
        self.assertIn("2 tag(s)", msg)
        self.assertIn("hotfix, wip", msg)


if __name__ == "__main__":
    unittest.main()
