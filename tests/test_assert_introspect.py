import unittest
from unittest import mock

from pyrunner.core import assert_introspect


class AssertIntrospectTests(unittest.TestCase):
    def test_simple_equality_captures_left_and_right(self):
        left = 404
        right = 200
        try:
            assert left == right
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["expr"], "left == right")
        self.assertEqual(details["op"], "==")
        self.assertEqual(details["left"], {"repr": "404", "type": "int"})
        self.assertEqual(details["right"], {"repr": "200", "type": "int"})

    def test_string_equality_produces_unified_diff(self):
        a = "hello\nworld\n"
        b = "hello\nthere\n"
        try:
            assert a == b
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertIn("-world", details["diff"])
        self.assertIn("+there", details["diff"])

    def test_dict_diff_reports_missing_and_extra_keys(self):
        left = {"a": 1, "b": 2}
        right = {"a": 1, "c": 3}
        try:
            assert left == right
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["diff"], {"missing": ["'c'"], "extra": ["'b'"]})

    def test_call_in_expression_skips_value_resolution(self):
        def get():
            return 1

        try:
            assert get() == 2
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["expr"], "get() == 2")
        self.assertIsNone(details["left"])
        self.assertIsNone(details["right"])
        self.assertIsNone(details["op"])

    def test_property_attribute_is_not_evaluated_again_by_introspection(self):
        calls = []

        class Lazy:
            @property
            def value(self):
                calls.append(1)
                return 42

        obj = Lazy()
        try:
            assert obj.value == 99
        except AssertionError as e:
            # the assert statement itself already evaluated the property
            # once, via normal Python semantics, before this except block
            # runs -- what we're verifying is that introspection does NOT
            # trigger a second evaluation of it.
            calls_before_introspection = len(calls)
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(len(calls), calls_before_introspection)
        self.assertIsNone(details["left"])

    def test_plain_instance_attribute_is_resolved(self):
        class Point:
            def __init__(self):
                self.x = 5

        p = Point()
        try:
            assert p.x == 6
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["left"], {"repr": "5", "type": "int"})

    def test_bare_truthy_assert_reports_names(self):
        flag = False
        try:
            assert flag
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["names"], {"flag": "False"})

    def test_chained_comparison_reports_expr_only(self):
        try:
            assert 1 < 2 < 0
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["expr"], "1 < 2 < 0")
        self.assertIsNone(details["op"])
        self.assertIsNone(details["left"])

    def test_explicit_raise_of_assertion_error_returns_none(self):
        try:
            raise AssertionError("boom")
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertIsNone(details)

    def test_exception_with_no_traceback_returns_none(self):
        self.assertIsNone(assert_introspect.build_assert_details(AssertionError("x")))

    def test_source_unavailable_returns_none(self):
        try:
            exec("assert 1 == 2", {}, {})
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertIsNone(details)

    def test_never_raises_when_internals_error(self):
        with mock.patch.object(assert_introspect, "_parse_cached", side_effect=RuntimeError("boom")):
            try:
                assert 1 == 2
            except AssertionError as e:
                details = assert_introspect.build_assert_details(e)
        self.assertIsNone(details)

    def test_large_int_subscript_on_list_is_resolved(self):
        items = [10, 20, 30]
        try:
            assert items[1] == 99
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["left"], {"repr": "20", "type": "int"})

    def test_unary_minus_on_plain_int_literal_is_resolved(self):
        try:
            assert -5 == -6
        except AssertionError as e:
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(details["left"], {"repr": "-5", "type": "int"})

    def test_unary_minus_on_custom_numeric_subclass_is_not_resolved(self):
        calls = []

        class SneakyInt(int):
            def __neg__(self):
                calls.append("EXECUTED")
                return int.__neg__(self)

        x = SneakyInt(5)
        try:
            assert -x == -6
        except AssertionError as e:
            calls_before = len(calls)
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(len(calls), calls_before)
        self.assertIsNone(details["left"])

    def test_subscript_with_hostile_key_is_not_resolved(self):
        calls = []

        class EvilKey:
            def __hash__(self):
                calls.append("HASH")
                return 1

            def __eq__(self, other):
                calls.append("EQ")
                return True

        d = {1: "a"}
        k = EvilKey()
        try:
            assert d[k] == "b"
        except AssertionError as e:
            calls_before = len(calls)
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(len(calls), calls_before)
        self.assertIsNone(details["left"])

    def test_dict_diff_with_hostile_key_is_not_computed(self):
        calls = []

        class HostileKey:
            def __init__(self, label):
                self.label = label

            def __hash__(self):
                calls.append("HASH")
                return 42

            def __eq__(self, other):
                calls.append("EQ")
                return isinstance(other, HostileKey) and self.label == other.label

        left = {HostileKey("a"): 1}
        right = {HostileKey("b"): 2}
        try:
            assert left == right
        except AssertionError as e:
            calls_before = len(calls)
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(len(calls), calls_before)
        self.assertIsNone(details["diff"])

    def test_set_diff_with_hostile_element_is_not_computed(self):
        calls = []

        class HostileElement:
            def __hash__(self):
                calls.append("HASH")
                return 1

            def __eq__(self, other):
                calls.append("EQ")
                return self is other

        left = {HostileElement()}
        right = {HostileElement()}
        try:
            assert left == right
        except AssertionError as e:
            calls_before = len(calls)
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(len(calls), calls_before)
        self.assertIsNone(details["diff"])

    def test_class_attribute_with_custom_getattr_is_not_probed(self):
        calls = []

        class Weird:
            def __getattr__(self, name):
                calls.append(name)
                raise AttributeError(name)

        class Foo:
            attr = Weird()

        obj = Foo()
        try:
            assert obj.attr == 99
        except AssertionError as e:
            calls_before = list(calls)
            details = assert_introspect.build_assert_details(e)
        self.assertEqual(calls, calls_before)
        # Weird has no __get__, so it genuinely isn't a descriptor --
        # unlike the property-guard test above, resolution SHOULD
        # proceed normally here. The property under test is that the
        # safety CHECK itself doesn't trigger __getattr__ (verified by
        # the calls assertion above), not that the value stays hidden.
        self.assertIsNotNone(details["left"])


if __name__ == "__main__":
    unittest.main()
