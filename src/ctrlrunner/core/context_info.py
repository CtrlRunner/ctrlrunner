"""
Exposes the current test's id/attempt number to fixture code, so
built-in Playwright fixtures (and user fixtures) can make
attempt-aware decisions -- e.g. only start tracing from the first
retry onward ("on-first-retry" mode). State is module-level per worker
process, same reasoning as steps.py/annotations.py: a worker runs
exactly one test at a time.
"""

_test_id = None
_attempt = None
_properties: dict = {}


def begin_test(test_id, attempt):
    global _test_id, _attempt, _properties
    _test_id = test_id
    _attempt = attempt
    _properties = {}


def current_test_id():
    return _test_id


def current_attempt():
    return _attempt


def record_property(key, value):
    """pytest-record_property equivalent: call from a test
    body or fixture to attach metadata to the CURRENT test's result --
    lands in Result.properties, so it shows up as a JUnit <property>
    and in the JSON/HTML reports. Reset per attempt; the attempt that
    produces the final result is the one whose properties ship."""
    _properties[str(key)] = str(value)


def collect_properties() -> dict:
    return dict(_properties)
