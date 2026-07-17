# Migrating from pytest

[← Back to README](../README.md)

`ctrlrunner.migrate` automates the bulk of a pytest -> ctrlrunner
conversion — decorators, markers, parametrize (including `indirect=`,
which ctrlrunner supports natively — the decorator passes through
verbatim and the target fixture gets a `request` parameter added if
missing, even cross-file in `conftest.py`), test classes, runtime
`pytest.skip/fail/xfail` calls, pytest-playwright fixtures, imports,
and `pytest_addoption`/`pytestconfig.getoption` (renamed to
`ctrlrunner_addoption`/`get_option`, ctrlrunner's typed-CLI-flag
equivalent — see README's "Custom options" section).
Whatever has no ctrlrunner equivalent gets a
`# TODO(ctrlrunner-migrate): ...` comment in place plus a summary report.

```
pip install libcst                             # migration-time only
python -m ctrlrunner.migrate tests/              # dry-run: diffs + report
python -m ctrlrunner.migrate tests/ --write      # apply in place
```

See [MIGRATION.md](MIGRATION.md) for the full conversion
table and the post-migration checklist.

## Explicitly not included

- **pytest hooks** (other than `pytest_addoption`, which IS converted — see above) — skipped by design; ctrlrunner's own event model is the only supported extension point.
