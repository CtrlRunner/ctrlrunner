# Migrating from pytest

[← Back to README](../README.md)

`pyrunner.migrate` automates the bulk of a pytest -> pyrunner
conversion — decorators, markers, parametrize (including indirect,
cross-file into `conftest.py`), test classes, runtime
`pytest.skip/fail/xfail` calls, pytest-playwright fixtures, imports.
Whatever has no pyrunner equivalent gets a
`# TODO(pyrunner-migrate): ...` comment in place plus a summary report.

```
pip install libcst                             # migration-time only
python -m pyrunner.migrate tests/              # dry-run: diffs + report
python -m pyrunner.migrate tests/ --write      # apply in place
```

See [MIGRATION.md](MIGRATION.md) for the full conversion
table and the post-migration checklist.

## Explicitly not included

- **pytest hooks** — skipped by design; pyrunner's own event model is the only supported extension point.
