---
name: github-code-quality
description: "Use when the user asks to check, read, triage, or fix GitHub Code Scanning (CodeQL security) or Code Quality findings for a repo, or asks about 'code quality API', 'security findings', 'code scanning alerts', or why GHAS findings aren't accessible. Covers the exact gh api endpoints, their quirks (GHAS licensing, read-only Code Quality API, dismiss patterns), and how to triage findings against real code instead of trusting the rule description alone."
---

# GitHub Code Quality & Code Scanning

Two distinct GitHub features live under similar-sounding names. Don't confuse them.

| | Code Scanning (security) | Code Quality |
|---|---|---|
| API root | `/repos/{owner}/{repo}/code-scanning/*` | `/repos/{owner}/{repo}/code-quality/*` |
| What it flags | Security vulnerabilities (CodeQL security queries) | Maintainability/reliability (CodeQL quality queries) |
| List findings | `GET .../code-scanning/alerts` | `GET .../code-quality/findings` |
| Get one | `GET .../code-scanning/alerts/{number}` | `GET .../code-quality/findings/{number}` |
| **Dismiss via API** | **Yes** — `PATCH .../alerts/{number}` | **No** — PATCH/POST/PUT all 404. Web UI only (Security tab) as of this writing. |
| Numbering | Own counter | Separate counter, does NOT share numbers with code-scanning alerts |
| Requires | GitHub Advanced Security (GHAS) | Same |

There is **no** `/repos/{owner}/{repo}/code-quality` (no `/findings` suffix) — that 404s. Always include `/findings`.

## The GHAS licensing trap (private repos)

`code-scanning/alerts` and `code-quality/findings` both 403 with `"Advanced Security must be enabled for this repository to use code scanning"` on **private** repos unless the org has paid for GitHub Advanced Security. A workflow named "CodeQL Setup" can show green in Actions while its results are silently discarded — a successful *run* does not mean the *alerts* are stored or queryable.

Diagnose with:
```bash
gh api repos/{owner}/{repo} --jq '{private, visibility}'
gh api orgs/{org} --jq '{advanced_security_enabled_for_new_repositories, plan}'
```
If `private: true` and the org plan is `free`, that's the whole story. Two fixes: pay for GHAS, or make the repo public (GHAS is free for public repos). Making a repo public is a real, user-facing decision — confirm with the user before doing it, it isn't a technical no-op.

## Triggering / configuring a scan

CodeQL's "default setup" (GitHub-managed, not a workflow file in the repo — shows as `dynamic/github-code-scanning/codeql` in Actions) is configured via:
```bash
gh api repos/{owner}/{repo}/code-scanning/default-setup   # GET: state, languages, query_suite (default|extended)

gh api -X PATCH repos/{owner}/{repo}/code-scanning/default-setup \
  -f state=configured -f query_suite=default \
  -f 'languages[]=python' -f 'languages[]=javascript-typescript' -f 'languages[]=actions'
# -> {"run_id": ..., "run_url": ...} -- triggers an immediate scan
```
`query_suite=extended` pulls in more maintainability/quality-tagged rules than `default`. Visibility changes (private→public) can silently reset `state` to `not-configured` — re-check and re-PATCH after changing visibility.

Watch the triggered run, then findings appear once it completes:
```bash
gh run watch <run_id> --repo {owner}/{repo} --exit-status
```

## Fetching findings

Always paginate — both endpoints cap at ~30-100 per page:
```bash
gh api --paginate repos/{owner}/{repo}/code-scanning/alerts > alerts.json
gh api --paginate repos/{owner}/{repo}/code-quality/findings > findings.json
```
Useful triage query (works on either, field names match) — group by file, then by rule, before reading anything:
```bash
python3 -c "
import json
from collections import Counter
data = json.load(open('findings.json'))
print('by file:', Counter(f['location']['path'] for f in data).most_common())
print('by rule:', Counter(f['rule']['id'] for f in data).most_common())
"
```
**Check `dependabot/alerts` and `secret-scanning/alerts` too** while you're at it — same GHAS gate, easy to forget:
```bash
gh api repos/{owner}/{repo}/dependabot/alerts
gh api repos/{owner}/{repo}/secret-scanning/alerts   # 404 "disabled" if the feature toggle is off (separate from GHAS)
```

## Triage: read the actual code before trusting the rule description

CodeQL's rule `full_description`/`help` text describes the *general* vulnerability class, not this specific instance. A meaningful chunk of real-world findings are false positives from known CodeQL blind spots — verify against the real code every time, don't just relay the rule text:

- **Minified/bundled build artifacts** (committed `dist/`, Vite/webpack output, `_static/*.html`) — single-letter minified var names trigger `use-before-declaration`, `trivial-conditional`, `automatic-semicolon-insertion` en masse. If the finding's `path` is a build artifact, check whether the *source* (`src/`, `frontend/src/`) is separately linted (tsc/Biome/eslint) — if so, this is noise, not a real quality signal.
- **Dynamic/duck-typed dispatch** (Python) — a helper that calls a callback with N args chosen by `inspect.signature()` at runtime (backward-compat shims, plugin hooks) confuses CodeQL's static call-graph resolution: it can flag `call/wrong-arguments` by conflating two *different* callables (e.g. two test fixtures with different arities) as reachable from both call sites, when a runtime guard ensures each is only ever called the right way.
- **`unittest.TestCase.assertRaises`/similar context managers that suppress exceptions** — CodeQL's control-flow analysis doesn't always model a custom `__exit__` returning truthy to swallow a matching exception, so code after the `with` block gets flagged `unreachable-statement` even though it runs every time.
- **`sys.exit()` / other `NoReturn` calls** — not always modeled as terminating control flow, producing spurious `mixed-returns`.
- **Existing containment/validation checks CodeQL doesn't recognize as sanitizers** — e.g. `Path.resolve()` + `path.relative_to(root)` in a `try/except ValueError: return 403` is a real, correct path-traversal guard; CodeQL's taint tracker may not have a model for `relative_to()` as a sanitizer and still flags the downstream file read as `path-injection`. Read the actual containment logic before agreeing with the alert.
- **Deliberately large regex character ranges** (e.g. the entire UTF-16 surrogate block `\ud800-\udfff` for XML validity filtering) trip `overly-large-range` — check whether the range is a real, meaningful Unicode block before assuming it's a typo.
- **Intentional unused imports with `# noqa: F401`** (re-exports, feature-detection `try: import X` patterns) — ruff already suppresses these; CodeQL doesn't read ruff's noqa comments and flags them anyway. Don't "fix" these by deleting the import — check for a noqa comment first.
- **Names bound but never read by design** (e.g. a class defined inside a test purely to trigger a decorator's side effect / raise during registration) — flagged `unused-local-variable`, but the point of the code is the side effect, not the binding.
- **`py/import-and-import-from`: package + submodule imported for different purposes** — `import unittest` (for `unittest.TestCase`) alongside `from unittest import mock` (for the `mock.` alias) is idiomatic, not a duplicate; same for a function-local `import pkg.mod as alias` used for introspection (`hasattr(alias, ...)`) coexisting with a top-level `from pkg.mod import name`. Two genuinely different bindings, not the same name imported twice.
- **`py/not-named-self` on a test that deliberately verifies the framework doesn't require `self`** — if the test's whole point is proving a method named e.g. `page` still works, renaming the parameter to satisfy the linter defeats the test. Check what the test asserts before renaming.

**A `# noqa` comment's stated justification is a claim, not a fact — verify it too.** Don't just check that the noqa exists; check whether the reason it gives is still true. Example: `from .sharding import lookup_median_durations, lpt_shard  # noqa: F401 -- lpt_shard re-exported` looked like the documented "intentional re-export" false positive above — until `grep -rn "lpt_shard"` across the repo showed every other caller (tests, `worker_budget.py`) imports `lpt_shard` straight from `.sharding`, never through this module, and `lpt_shard(` is never even called here (the code actually calls a *different*, private `_lpt_shard_weighted` via `group_aware_shard`). The "re-exported" claim was stale from an earlier refactor; the import was genuinely dead and the finding was correct. Grep for real external usage before accepting a suppression comment's reasoning.

## Eliminating a false positive instead of just documenting it

Some false positives can be made to disappear with a small, behavior-preserving rewrite that changes the code's *shape* enough that the query no longer pattern-matches it — better than leaving noise on the books when the API can't dismiss it:

- **Collapse dual call sites into one variadic call.** `_call_on_failure`'s two branches (`on_failure(value, prefix, outcome)` / `on_failure(value, prefix)`) each looked like a fixed-arity call CodeQL could cross-check against every possible callee — build the args as a tuple once and call `on_failure(*args)` from a single site instead; a `*args` unpack isn't something the arity checker can flag.
- **Swap `from pkg import submodule` for a plain `import pkg.submodule as name`** when `py/import-and-import-from` fires on a package+submodule pair used for different purposes (e.g. `import unittest` + `from unittest import mock`) — same runtime binding, but no `ImportFrom` node left for the query to match against the sibling `Import`.
- **Rename an intentionally-unused binding to `_`** (e.g. a class defined only to trigger a decorator's registration side effect) — the underscore-means-throwaway convention is honored by `py/unused-local-variable` the same way it is by ruff/pylint.

**Know when to stop, though.** A rewrite is only worth it if it's a genuine no-op on behavior *and* doesn't trip some other enforced check. Converting `sys.exit(1)` to `raise SystemExit(1)` inside `except` blocks was tried for `py/mixed-returns` (the hypothesis: CodeQL models `raise` as terminating control flow but not always `sys.exit()`) — it produced 15 new ruff `B904` violations (`raise ... from err` required inside `except`) that would have failed CI's `ruff check .`, for a CodeQL fix that was never confirmed to work in the first place. Reverted. Trading a *guaranteed* regression in an enforced check for an *unverified* fix elsewhere is a bad trade — leave it as a documented false positive instead.

## Dismissing alerts (code-scanning only)

```bash
gh api -X PATCH repos/{owner}/{repo}/code-scanning/alerts/{number} \
  -f state=dismissed \
  -f dismissed_reason="false positive" \
  -f dismissed_comment="<why, be specific and cite the actual guard/check>"
```
`dismissed_reason` must be one of: `false positive`, `won't fix`, `used in tests`.
**`dismissed_comment` is capped at 280 characters** — the API 422s with `"Only 280 characters are allowed"` if you go over; keep it tight, cite the specific line/mechanism, not the general argument.

**Do this one call per finding, not in a shell `for` loop.** A `for num in $IDS; do gh api ...; done` loop has silently failed to actually iterate in practice (the whole ID list got passed as a single malformed argument) with no visible error because stderr was redirected — always verify a sample of "dismissed" IDs afterward with a plain `GET`, and prefer explicit, individually-issued commands (batched as multiple tool calls, not a bash loop) so each dismissal is independently visible and its result checkable.

`code-quality/findings` has no dismiss endpoint — tell the user it needs the Security tab UI (Code Quality section) if they want it dismissed, don't attempt PATCH/POST workarounds.

## Fixing real findings

For genuine (non-false-positive) findings: fix at the root cause, matching this project's own conventions (see root `CLAUDE.md`/`CONTRIBUTING.md`). Re-run `ruff check`, `ruff format --check`, `ty check`, and the full test suite after any code-quality cleanup — a "safe mechanical fix" (unused import, dead assignment) can still break something if a linter's static view misses a real reference (e.g. via `getattr`, string-based dynamic lookup, or a re-export contract).
