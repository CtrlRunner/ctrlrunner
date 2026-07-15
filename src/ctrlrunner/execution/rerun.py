"""
Rerun workflows --
--last-failed, --failed-from, --changed-since. All three are pure
pre-population of --test-id: zero new selection logic in selection.py,
which already does exactly what's needed once the right test_ids are
resolved.
"""

import json
import subprocess
from pathlib import Path


class RerunError(Exception):
    """Raised for a rerun request that can't be resolved (no previous
    report found, git unavailable, a bad ref, ...) -- caught by the CLI
    and turned into a clear error message + exit 1, never a raw
    traceback."""


def load_failed_test_ids(report_json_path: Path) -> list[str]:
    """Reads a results.json (the JsonReporter's own output shape) and
    returns the ids of every test with outcome == 'failed'. Deliberately
    excludes any future 'quarantined_failure' outcome --
    rerunning known-flaky-and-quarantined tests isn't what this is for."""
    if not report_json_path.exists():
        raise RerunError(
            f"No JSON report found at {report_json_path}. "
            f"(--last-failed/--failed-from need a previous run's results.json -- "
            f"run the tests at least once first.)"
        )
    try:
        data = json.loads(report_json_path.read_text())
    except json.JSONDecodeError as e:
        raise RerunError(f"Could not parse {report_json_path} as JSON: {e}") from e
    failed = [t for t in data.get("tests", []) if t.get("outcome") == "failed"]
    if any("id" not in t for t in failed):
        # Same contract as the parse errors above: malformed report in,
        # RerunError out -- never a raw KeyError.
        raise RerunError(
            f"Malformed report at {report_json_path}: a failed test entry has no 'id' field."
        )
    return [t["id"] for t in failed]


def _validate_git_ref(git_ref: str) -> None:
    """Rejects a ref beginning with '-' (OWASP A03: git argument
    injection). `git_ref` comes straight from the --changed-since CLI
    flag; passed positionally, a value like '--output=/tmp/x' would be
    parsed by git as an OPTION, not a revision. There's no shell here
    (argument list, not shell=True), so this plus the '--' end-of-options
    separator below is all that's needed to keep it strictly a ref."""
    if git_ref.startswith("-"):
        raise RerunError(
            f"Invalid git ref {git_ref!r}: refs may not start with '-' "
            f"(--changed-since expects a revision, not a git option)."
        )


def resolve_changed_files(git_ref: str, cwd: str | None = None) -> list[str]:
    """Returns paths (as git reports them, repo-root-relative) changed
    since `git_ref`, PLUS every untracked file -- deliberately just
    `git diff --name-only` + `git ls-files --others --exclude-standard`,
    no import-graph analysis, so this can over-select (rerun tests in a
    file that changed but whose specific change didn't affect them) but
    never under-select, the safe direction to be wrong in for a
    "did I break anything" workflow. Untracked files matter here
    specifically because a brand-new test file has nothing to diff
    against yet, but is exactly the kind of change --changed-since
    exists to catch."""
    _validate_git_ref(git_ref)
    try:
        # Trailing '--' is an end-of-options separator: it forces git to
        # treat git_ref strictly as a revision, never as a pathspec/option.
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", git_ref, "--"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except FileNotFoundError as e:
        raise RerunError("git is not available on PATH -- --changed-since requires git.") from e
    if diff_result.returncode != 0:
        raise RerunError(f"git diff --name-only {git_ref} failed: {diff_result.stderr.strip()}")

    try:
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except FileNotFoundError as e:
        raise RerunError("git is not available on PATH -- --changed-since requires git.") from e
    if untracked_result.returncode != 0:
        raise RerunError(f"git ls-files --others failed: {untracked_result.stderr.strip()}")

    changed = [line.strip() for line in diff_result.stdout.splitlines() if line.strip()]
    untracked = [line.strip() for line in untracked_result.stdout.splitlines() if line.strip()]

    seen = set()
    combined = []
    for f in changed + untracked:
        if f not in seen:
            seen.add(f)
            combined.append(f)
    return combined


def resolve_repo_root(cwd: str | None = None) -> str:
    """Returns the absolute repo root via `git rev-parse --show-toplevel`
    -- `git diff --name-only` always prints paths relative to the repo
    root regardless of the caller's cwd, so matching those paths back to
    TestItem.source_path must resolve against the SAME root, not the
    process's current working directory (running ctrlrunner from a
    subdirectory previously made every --changed-since comparison miss)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except FileNotFoundError as e:
        raise RerunError("git is not available on PATH -- --changed-since requires git.") from e
    if result.returncode != 0:
        raise RerunError(
            f"git rev-parse --show-toplevel failed: {result.stderr.strip()} "
            f"(--changed-since requires running inside a git repository)"
        )
    return result.stdout.strip()


def match_changed_files_to_test_ids(
    changed_files: list[str], all_tests, repo_root: str
) -> list[str]:
    """File-level granularity: a test whose source_path resolves to one
    of the changed files selects every test in that file. `all_tests`
    is the currently-discovered TestItem list (needs source_path)."""
    repo_root_path = Path(repo_root).resolve()
    changed_abs = set()
    for f in changed_files:
        try:
            changed_abs.add((repo_root_path / f).resolve())
        except OSError:
            continue
    matched = []
    for item in all_tests:
        if item.source_path is not None and item.source_path.resolve() in changed_abs:
            matched.append(item.id)
    return matched


def expand_serial_groups(test_ids: list[str], all_tests) -> list[str]:
    """A serial class (@test_class(serial=True)) is an atomic unit --
    rerunning only its failed members would execute a partial group
    (skip-on-fail and group retries over a subset the author never
    intended). Any rerun selection touching a serial group therefore
    expands to the whole group, members appended in registration
    (definition) order. Explicit --test-id selections are NOT expanded
    -- an explicit id is the user's own call."""
    selected = set(test_ids)
    touched = {t.serial_group for t in all_tests if t.serial_group is not None and t.id in selected}
    out = list(test_ids)
    for t in all_tests:
        if t.serial_group in touched and t.id not in selected:
            selected.add(t.id)
            out.append(t.id)
    return out


def match_rerun_ids(requested_ids: list[str], current_test_ids: list[str]) -> list[str]:
    """Exact match first. For a requested id not found verbatim among
    the CURRENT collection (e.g. a parametrized id whose param set has
    since changed, so the exact bracketed suffix no longer exists),
    falls back to the base id (everything before the first '[') and
    reruns every current variant of that test -- never silently drops
    it just because the exact suffix moved."""
    current_set = set(current_test_ids)
    resolved = []
    for rid in requested_ids:
        if rid in current_set:
            resolved.append(rid)
            continue
        base = rid.split("[", 1)[0]
        # A stored id that still carries a "[project] " prefix (it
        # never should by the time it reaches here -- identity is
        # supposed to be the raw id plus a separate project column --
        # but defend against it anyway) makes rid.split("[", 1)[0] the
        # EMPTY STRING, since the prefix itself starts with "[". Without
        # this guard, an empty base can't match any real current id
        # (none start with "[") so this just silently resolves to
        # nothing for that id -- correct in effect, but only by
        # accident; skip it explicitly rather than relying on that.
        if not base:
            continue
        resolved.extend(
            tid for tid in current_test_ids if tid == base or tid.startswith(base + "[")
        )

    seen = set()
    deduped = []
    for tid in resolved:
        if tid not in seen:
            seen.add(tid)
            deduped.append(tid)
    return deduped
