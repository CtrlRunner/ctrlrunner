"""
No manual browser/context/page fixtures needed anymore -- trace and
screenshot capture are controlled entirely by --trace/--screenshot CLI
flags (or ctrlrunner.toml), same idea as Playwright TS's CLI:

    python -m ctrlrunner examples --trace on-first-retry --screenshot only-on-failure
"""
import re

from playwright.sync_api import expect

from ctrlrunner import test


@test(timeout=15, case_id="TC-EX-001", tags={"smoke"})
def test_example_dot_com(page):
    page.goto("https://example.com")
    assert page.title() == "Example Domain"


@test(timeout=15, case_id="TC-EX-002", tags={"smoke"})
def test_playwright_dev(page):
    page.goto("https://playwright.dev")
    expect(page).to_have_title(re.compile("Playwrightttt"))


@test(timeout=15, case_id="TC-EX-003", tags={"smoke"})
def test_playwright_dev_url(page):
    page.goto("https://playwright.dev")
    expect(page).to_have_url("https://playwright.dev/")


@test(timeout=15, case_id="TC-EX-004", tags={"smoke"})
def test_playwright_dev_get_started_visible(page):
    page.goto("https://playwright.dev")
    expect(page.get_by_role("link", name="Get started")).to_be_visible()


@test(timeout=15, case_id="TC-EX-005", tags={"smoke"})
def test_playwright_dev_heading_text(page):
    page.goto("https://playwright.dev")
    expect(page.locator("h1")).to_contain_text("Playwrightttt")


@test(timeout=15, case_id="TC-EX-006", tags={"smoke"})
def test_playwright_dev_heading_count(page):
    page.goto("https://playwright.dev")
    expect(page.locator("h1")).to_have_count(1)
