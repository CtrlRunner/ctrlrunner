import time

from playwright.sync_api import Page, sync_playwright
from ctrlrunner import fixture, test, parametrize, step, skip, fail, fixme, slow

calls = {"session_setup": 0, "session_teardown": 0}


@fixture(scope="session")
def fake_browser():
    calls["session_setup"] += 1
    yield {"name": "fake-browser"}
    calls["session_teardown"] += 1


def _fake_capture(page: Page, prefix):
    path = f"{prefix}.png"
    page.screenshot(path=path)
    return path


@fixture(scope="function", on_failure=_fake_capture)
def fake_page(fake_browser):
    page = {"browser": fake_browser["name"], "url": None}
    yield page


@test(timeout=2, case_id="TC-300")
def test_captures_artifact_on_failure(fake_page):
    fake_page["url"] = "https://example.com/broken"
    assert False, "forced failure to trigger on_failure capture"


@test(timeout=2, case_id="TC-001", tags={"smoke", "team_3"})
def test_passes(fake_page):
    fake_page["url"] = "https://example.com"
    assert fake_page["url"] == "https://example.com"


@test(timeout=2, case_id="TC-002", tags={"regression", "team_3"})
def test_fails(fake_page):
    assert 1 == 2


@test(timeout=2, case_id="TC-003", tags={"smoke", "team_3"})
def test_hangs(fake_page):
    # Should get hard-killed by the Job Object after ~2s + 5s buffer,
    # and the rest of its batch should be requeued onto a new worker.
    time.sleep(30)


@test(timeout=2, case_id="TC-004", tags={"smoke", "team_3"})
def test_after_hang(fake_page):
    fake_page["url"] = "https://after.example"
    assert fake_page["url"] == "https://after.example"


@test(timeout=5, case_id="TC-500", tags={"smoke", "team_3"})
def test_skipped_via_runtime_condition(fake_page):
    skip(True, "not applicable in this environment")
    assert False, "should never run"


@test(timeout=5, case_id="TC-501", tags={"smoke", "team_3"})
def test_fixme_marks_known_broken(fake_page):
    fixme(True, "JIRA-999: fix once backend ships the new endpoint")
    assert False, "should never run"


@test(timeout=5, case_id="TC-502", tags={"smoke", "team_3"})
def test_fail_strict_reports_expected_failure(fake_page):
    fail(True, "JIRA-1000: known broken until fix ships", strict=True)
    assert False, "expected to fail -- should NOT break the build"


@test(timeout=5, case_id="TC-503", tags={"smoke", "team_3"})
def test_fail_strict_flags_unexpected_pass(fake_page):
    fail(True, "JIRA-1001: should still be broken", strict=True)
    assert True  # unexpectedly passes -> reported as "failed" (strict)


@test(timeout=5, case_id="TC-504")
def test_fail_non_strict_allows_unexpected_pass(fake_page):
    fail(True, "JIRA-1002: fix may have landed", strict=False)
    assert True  # unexpectedly passes -> stays "passed", flagged in properties


@test(timeout=2, case_id="TC-505")
def test_slow_extends_timeout(fake_page):
    slow(True, factor=5.0)
    time.sleep(3)  # would exceed the original 2s timeout without slow()
    assert True


# NOTE: decorators apply bottom-up, so @parametrize must sit closer to the
# function than @test -- it needs to attach _param_sets before @test reads it.
@test(timeout=2, case_id="TC-100-{locale}", tags={"smoke", "i18n"},
      properties={"owner": "sdet-team"})
@parametrize("locale", ["en-US", "uk-UA", "de-DE"])
def test_locale_switch(locale, fake_page):
    fake_page["url"] = f"https://example.com?locale={locale}"
    assert locale in fake_page["url"]


@test(timeout=5, case_id="TC-400")
def test_with_nested_steps(fake_page):
    with step("Navigate"):
        fake_page["url"] = "https://example.com/login"
    with step("Log in"):
        with step("Fill credentials"):
            fake_page["user"] = "alice"
        with step("Submit"):
            fake_page["submitted"] = True
    assert fake_page["submitted"]


@test(timeout=5, case_id="TC-401")
def test_step_failure_is_recorded_and_propagates(fake_page):
    with step("Navigate"):
        fake_page["url"] = "https://example.com"
    with step("This step fails"):
        assert fake_page["url"] == "https://wrong.example"


_flaky_attempts = {"count": 0}


@test(timeout=2, case_id="TC-200", retries=2)
def test_flaky_passes_on_third_try(fake_page):
    _flaky_attempts["count"] += 1
    assert _flaky_attempts["count"] >= 3


@test(timeout=2, case_id="TC-201", retries=1)
def test_flaky_always_fails(fake_page):
    assert False


@fixture(scope="session")
def custom_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _capture_custom_screenshot(page: Page, prefix):
    path = f"{prefix}.png"
    page.screenshot(path=path)
    return path


@fixture(scope="function", on_failure=_capture_custom_screenshot)
def custom_page(custom_browser):
    page = custom_browser.new_page()
    yield page
    page.close()


@test(timeout=15, case_id="TC-600")
def test_custom_browser_captures_screenshot_on_failure(custom_page):
    custom_page.goto("https://example.com")
    assert False, "forced failure to confirm custom on_failure capture with a real browser"
