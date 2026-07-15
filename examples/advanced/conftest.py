"""
Shared fixtures for every test_*.py under examples/advanced/. Discovered
and imported automatically by the orchestrator before any test module --
no explicit import needed in the test files themselves.
"""
from ctrlrunner import fixture

module_setup_log = []


@fixture(scope="module")
def module_resource():
    """One instance per test module per worker, not per test. Torn down
    when the worker moves on to a different module."""
    module_setup_log.append("setup")
    yield {"connections": 0}
    module_setup_log.append("teardown")


@fixture(scope="function", autouse=True)
def audit_log():
    """Runs for every test automatically, even though no test lists it
    as a parameter -- useful for things like per-test logging, clearing
    global state, or asserting no leaked resources."""
    audit_log_calls.append("before")
    yield
    audit_log_calls.append("after")


audit_log_calls = []
