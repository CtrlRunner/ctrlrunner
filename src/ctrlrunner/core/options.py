"""
Per-process store for user-declared run options (ctrlrunner_addoption).

The CLI seeds this once in the main process (before any --list/rerun
module imports), and run_worker seeds it in each spawned worker BEFORE
test/conftest modules are imported there -- so module-level
`get_option(...)` in test files works everywhere. Same module-global
pattern as context_info.py and playwright_fixtures._config: state is
per worker process, set once, read anywhere (tests, fixtures, page
objects).

One caveat, main-process only: conftest.py module level runs once
during option-declaration collection, BEFORE the store is seeded --
`get_option` there returns defaults. Read options inside fixtures/
tests/functions, not at conftest module level. (In workers, seeding
precedes every import, so the caveat doesn't exist.)

Values must be picklable -- they ride the spawned worker's args tuple.
"""

_options: dict = {}


def _normalize(name: str) -> str:
    # get_option("--env"), get_option("env"), and get_option("my-opt")
    # all address the same key -- matching pytestconfig.getoption's
    # tolerance for the flag-string and dest-name forms.
    return name.lstrip("-").replace("-", "_")


def set_options(options: dict | None) -> None:
    """Replaces the whole store (None clears it). Called once per
    process by the CLI / run_worker -- not by user code."""
    global _options
    _options = dict(options or {})


def get_option(name: str, default=None):
    """The value of a declared or [ctrlrunner.options]-configured
    option. `default` applies only when the key is ABSENT from the
    store -- a declared option that resolved to None is present, so
    get_option("env", "fallback") returns None then (dict semantics,
    same as pytestconfig.getoption)."""
    return _options.get(_normalize(name), default)


def get_options() -> dict:
    """A copy of the whole store."""
    return dict(_options)
