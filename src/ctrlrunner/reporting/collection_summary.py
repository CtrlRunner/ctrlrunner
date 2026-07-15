"""
A one-line "what did we collect" summary printed before a real run
starts, regardless of --reporter (JsonReporter deliberately prints
nothing else, so this is a plain print(), not a ConsoleReporter
method -- it's the only way this shows up for every reporter choice).

Only uses fields known at SELECTION time (module, from TestItem.id;
tags, from TestItem.tags) -- quarantine/outcome aren't known yet, so
they're deliberately not part of this summary.
"""

from collections import Counter


def format_collection_summary(tests: list) -> str:
    total = len(tests)
    modules = {t.id.partition("::")[0] for t in tests}
    test_word = "test" if total == 1 else "tests"
    module_word = "module" if len(modules) == 1 else "modules"
    line = f"Collected {total} {test_word} across {len(modules)} {module_word}"

    tag_counts = Counter(tag for t in tests for tag in t.tags)
    if tag_counts:
        breakdown = ", ".join(f"{count} tagged {tag}" for tag, count in sorted(tag_counts.items()))
        line += f" ({breakdown})"

    return line
