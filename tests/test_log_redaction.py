import unittest

from ctrlrunner.reporting.log_redaction import (
    REDACTED,
    redact_log_entries,
    redact_text,
    resolve_redaction_patterns,
)


class ResolveRedactionPatternsTests(unittest.TestCase):
    def test_defaults_enabled_when_no_config(self):
        patterns = resolve_redaction_patterns({})
        self.assertIsNotNone(patterns)
        self.assertGreater(len(patterns), 0)

    def test_disabled_returns_none(self):
        self.assertIsNone(resolve_redaction_patterns({"log_redaction": {"enabled": False}}))

    def test_extra_patterns_are_compiled_on_top_of_defaults(self):
        base = len(resolve_redaction_patterns({}))
        patterns = resolve_redaction_patterns({"log_redaction": {"patterns": ["MYCORP-[0-9]+"]}})
        self.assertEqual(len(patterns), base + 1)

    def test_bad_enabled_type_raises(self):
        with self.assertRaises(ValueError):
            resolve_redaction_patterns({"log_redaction": {"enabled": "yes"}})

    def test_bad_patterns_type_raises(self):
        with self.assertRaises(ValueError):
            resolve_redaction_patterns({"log_redaction": {"patterns": "not-a-list"}})

    def test_invalid_regex_raises(self):
        with self.assertRaises(ValueError):
            resolve_redaction_patterns({"log_redaction": {"patterns": ["(unclosed"]}})


class RedactTextTests(unittest.TestCase):
    def setUp(self):
        self.patterns = resolve_redaction_patterns({})

    def test_masks_password_assignment(self):
        out = redact_text("db password=hunter2 connected", self.patterns)
        self.assertNotIn("hunter2", out)
        self.assertIn(REDACTED, out)

    def test_masks_bearer_token(self):
        out = redact_text("Authorization: Bearer abcDEF123.ghiJKL", self.patterns)
        self.assertNotIn("abcDEF123", out)
        self.assertIn(REDACTED, out)

    def test_masks_github_token(self):
        out = redact_text("token ghp_0123456789abcdefghijABCDEFGHIJ", self.patterns)
        self.assertNotIn("ghp_0123456789abcdefghijABCDEFGHIJ", out)

    def test_leaves_clean_text_untouched(self):
        self.assertEqual(redact_text("nothing secret here", self.patterns), "nothing secret here")

    def test_none_and_empty_pass_through(self):
        self.assertIsNone(redact_text(None, self.patterns))
        self.assertEqual(redact_text("", self.patterns), "")


class RedactLogEntriesTests(unittest.TestCase):
    def setUp(self):
        self.patterns = resolve_redaction_patterns({})

    def test_masks_stdout_stderr_and_records(self):
        logs = [
            {
                "attempt": 1,
                "stdout": "api_key=SECRETVALUE",
                "stderr": "password: p@ss",
                "records": [{"level": "INFO", "name": "x", "message": "token=abc123"}],
                "truncated": False,
            }
        ]
        out = redact_log_entries(logs, self.patterns)
        self.assertNotIn("SECRETVALUE", out[0]["stdout"])
        self.assertNotIn("p@ss", out[0]["stderr"])
        self.assertNotIn("abc123", out[0]["records"][0]["message"])

    def test_none_patterns_is_noop(self):
        logs = [{"attempt": 1, "stdout": "password=hunter2", "stderr": "", "records": []}]
        out = redact_log_entries(logs, None)
        self.assertEqual(out[0]["stdout"], "password=hunter2")

    def test_empty_logs_pass_through(self):
        self.assertIsNone(redact_log_entries(None, self.patterns))
        self.assertEqual(redact_log_entries([], self.patterns), [])


if __name__ == "__main__":
    unittest.main()
