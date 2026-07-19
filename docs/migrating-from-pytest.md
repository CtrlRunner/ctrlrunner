# Migrating from pytest

[← Back to README](../README.md)

`ctrlrunner.migrate` automates the bulk of a pytest -> ctrlrunner
conversion — decorators, markers, parametrize (including `indirect=`,
which ctrlrunner supports natively — the decorator passes through
verbatim and the target fixture gets a `request` parameter added if
missing, even cross-file in `conftest.py`), test classes, runtime
`pytest.skip/fail/xfail` calls, pytest-playwright fixtures, imports,
`pytest_addoption`/`pytestconfig.getoption` (renamed to
`ctrlrunner_addoption`/`get_option`, ctrlrunner's typed-CLI-flag
equivalent — see README's "Custom options" section), and the six
session/test hooks — `pytest_configure`, `pytest_sessionfinish`,
`pytest_runtest_setup`/`teardown`/`logstart`/`logreport` — renamed to
their `ctrlrunner_*` equivalents with bodies kept as-is (ctrlrunner
passes pytest-shaped shim objects, see [hooks.md](hooks.md)) and
`@pytest.hookimpl` decorators stripped. Whatever has no ctrlrunner
equivalent gets a `# TODO(ctrlrunner-migrate): ...` comment in place
plus a summary report.

```
pip install libcst                             # migration-time only
python -m ctrlrunner.migrate tests/              # dry-run: diffs + report
python -m ctrlrunner.migrate tests/ --write      # apply in place
```

See [MIGRATION.md](MIGRATION.md) for the full conversion
table and the post-migration checklist.

## Explicitly not included

- Any pytest hook beyond the seven auto-renamed above — ctrlrunner has
  no equivalent; its event model ([event-model.md](event-model.md)) is
  the extension point for observing (not driving) a run. Note the
  renamed hooks' shim objects are a deliberate *subset* of pytest's
  (see [hooks.md](hooks.md)'s "Compatibility limits") — a migrated body
  touching pytest-only attributes (`item.session`, `report.sections`,
  `config.pluginmanager`, ...) fails loudly at first run and needs a
  manual rewrite, which is what the caveat TODO is for.
