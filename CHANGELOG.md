# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-15

Initial release.

### Added

- Real OS-process workers with hard-kill timeouts via Windows Job Objects (POSIX fallback for dev).
- Decorator-based test API: `@test`, `@fixture`, `@parametrize`, `@test_class`, dependency injection.
- Parallel scheduling with scoped worker budgets and serial-class support.
- Rerun workflows, flaky analytics, and quarantine management.
- Historical timing store and fixture/execution profiling.
- Console, JUnit XML, and self-contained HTML reporters.
- Code coverage integration.
- UI Mode: local web server with live test tree, report viewer, and trace/screenshot artifacts.
- `pytest` -> `pyrunner` source migration tool (`libcst`-based).
