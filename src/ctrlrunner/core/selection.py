"""
Pure-function test selection. This is the direct replacement for the
pytest_collection_modifyitems-based ID filtering: no plugin hook, no
collection-time mutation, just a function over the list of TestItem
that the CLI (or anything else -- a Copilot skill, a future web UI)
can call directly and test in isolation.
"""

import re
from collections.abc import Iterable

from .registry import TestItem


def select_tests(
    tests: list[TestItem],
    test_ids: Iterable[str] | None = None,
    case_ids: Iterable[str] | None = None,
    case_id_prefixes: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
    exclude_tags: Iterable[str] | None = None,
    grep: str | None = None,
    grep_not: str | None = None,
) -> list[TestItem]:
    """All filters are AND-ed together; each accepts multiple values (OR
    within that filter). Passing nothing returns the full list unchanged.

    - test_ids: exact match on TestItem.id (module::func[params])
    - case_ids: exact match on TestItem.case_id (e.g. "TC-100-chromium")
    - case_id_prefixes: match if case_id starts with any given prefix
      (e.g. "TC-100" selects every parametrized variant of TC-100)
    - tags: match if the test has at least one of the given tags
    - exclude_tags: DROP a test if it has at least one of the given tags
      (applied after every include filter; include and exclude are
      AND-ed like everything else)
    - grep: regex matched against TestItem.id (module::[Class::]func[params]);
      only tests whose id matches are kept
    - grep_not: regex matched against TestItem.id; matching tests are DROPPED
      (applied after grep, AND-ed like everything else)
    """
    selected = tests

    if test_ids is not None:
        wanted: set[str] = set(test_ids)
        selected = [t for t in selected if t.id in wanted]

    if case_ids:
        wanted = set(case_ids)
        selected = [t for t in selected if t.case_id in wanted]

    if case_id_prefixes:
        prefixes = tuple(case_id_prefixes)
        selected = [t for t in selected if t.case_id and t.case_id.startswith(prefixes)]

    if tags:
        wanted = set(tags)
        selected = [t for t in selected if t.tags & wanted]

    if exclude_tags:
        unwanted = set(exclude_tags)
        selected = [t for t in selected if not (t.tags & unwanted)]

    if grep:
        pattern = re.compile(grep)
        selected = [t for t in selected if pattern.search(t.id)]

    if grep_not:
        pattern = re.compile(grep_not)
        selected = [t for t in selected if not pattern.search(t.id)]

    return selected
