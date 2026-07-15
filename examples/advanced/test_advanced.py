from ctrlrunner import fixture, test
from examples.advanced.conftest import audit_log_calls


@fixture(scope="function", params=["chromium", "firefox", "webkit"])
def browser_type(request):
    # In a real suite this would launch the actual browser matching
    # request.param; kept as a plain string here so the example runs
    # deterministically without a real browser/network in this environment.
    return request.param


@test(timeout=5, case_id="TC-ADV-{browser_type}", tags={"cross-browser"})
def test_runs_on_every_browser(browser_type, module_resource):
    module_resource["connections"] += 1
    assert browser_type in ("chromium", "firefox", "webkit")


@test(timeout=5, case_id="TC-ADV-100")
def test_module_resource_is_shared_within_module(module_resource):
    # Runs after the parametrized test above (same module, same worker if
    # not split across workers) -- module_resource should already exist
    # and the connections counter should reflect prior tests in this module.
    assert "connections" in module_resource


@test(timeout=5, case_id="TC-ADV-200")
def test_audit_log_autouse_fired_without_being_requested():
    # This test does not list `audit_log` as a parameter at all, yet it
    # still ran because autouse=True.
    assert "before" in audit_log_calls
