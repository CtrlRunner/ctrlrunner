"""
Runtime test annotations, analogous to Playwright TS's test.skip() /
test.fail() / test.fixme() / test.slow(). Called from inside a test body
(not the @test decorator), because a test's fixture values -- including
parametrized ones like browser_type -- are only known once the function
is actually running, which is also when a runtime condition like
`browser_type == "firefox"` becomes available. This mirrors Playwright
TS's own runtime-conditional style, rather than Python's decorator-level
pytest.mark.skipif, which can't see fixture values at all.

State is module-level (not thread-local), same reasoning as steps.py: a
worker process runs exactly one test at a time.
"""


class SkipTest(Exception):
    def __init__(self, description: str | None = None):
        super().__init__(description or "skipped")
        self.description = description


class FixmeTest(Exception):
    def __init__(self, description: str | None = None):
        super().__init__(description or "fixme")
        self.description = description


_expected_failure: dict[str, bool | str | None] = {
    "active": False,
    "description": None,
    "strict": True,
}
_queue = None
_worker_id = None
_test_id = None


def begin_test(queue=None, worker_id=None, test_id=None):
    """Called by the worker before each test attempt."""
    global _queue, _worker_id, _test_id
    _queue, _worker_id, _test_id = queue, worker_id, test_id
    _expected_failure["active"] = False
    _expected_failure["description"] = None
    _expected_failure["strict"] = True


def skip(condition: bool = True, description: str | None = None):
    """Stops the test immediately; reported as 'skipped', not a failure.
    Nothing after this call runs if condition is true."""
    if condition:
        raise SkipTest(description)


def fixme(condition: bool = True, description: str | None = None):
    """Same runtime behavior as skip(), but reported as 'fixme' (known
    broken, needs attention) instead of 'skipped' (not applicable) --
    a different triage bucket in reports, not a different mechanism."""
    if condition:
        raise FixmeTest(description)


def fail(condition: bool = True, description: str | None = None, strict: bool = True):
    """Marks the rest of this test as expected to fail (pytest's xfail,
    named after Playwright TS's test.fail()). Must be called BEFORE the
    failure happens.

    - Test raises afterward -> reported as 'expected_failure', does not
      break the build.
    - Test does NOT raise (unexpectedly passes):
        - strict=True (default) -> reported as 'failed': an unexpected
          pass on a tracked bug is itself worth flagging.
        - strict=False -> reported as 'passed', with an
          'unexpected_pass' property for visibility without breaking CI
          (useful right after a fix ships, before removing the fail()
          call).
    """
    if condition:
        _expected_failure["active"] = True
        _expected_failure["description"] = description
        _expected_failure["strict"] = strict


def slow(condition: bool = True, factor: float = 3.0):
    """Extends this test's timeout by `factor` for this run. Call before
    the slow portion of the test; the orchestrator's watchdog recomputes
    its deadline on the next check after receiving this."""
    if condition and _queue is not None:
        _queue.put(("timeout_extended", _worker_id, _test_id, factor))


def record_suite_property(key, value):
    """pytest-record_testsuite_property equivalent: run-level
    metadata (environment name, build URL, ...) recorded from inside any
    test or fixture -- rendered as a <properties> block under
    <testsuite> and as suiteProperties in the JSON report. Streams to
    the orchestrator immediately, so unlike pytest+xdist it is never
    lost with parallel workers; across workers, last write per key
    wins."""
    if _queue is not None:
        _queue.put(("suite_property", _worker_id, str(key), str(value)))


def get_expected_failure() -> dict:
    return dict(_expected_failure)
