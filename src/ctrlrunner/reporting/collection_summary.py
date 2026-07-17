"""
A one-line "what did we collect" summary printed before a real run
starts, regardless of --reporter (JsonReporter deliberately prints
nothing else, so this is a plain print(), not a ConsoleReporter
method -- it's the only way this shows up for every reporter choice).

Only uses fields known at SELECTION time (source file, from
TestItem.id; tags, from TestItem.tags) -- quarantine/outcome aren't
known yet, so they're deliberately not part of this summary.
"""

from collections import Counter

from .grouping import group_by_file


def format_collection_summary(tests: list) -> str:
    total = len(tests)
    files = {group_by_file(t) for t in tests}
    test_word = "test" if total == 1 else "tests"
    file_word = "file" if len(files) == 1 else "files"
    line = f"Collected {total} {test_word} across {len(files)} {file_word}"

    tag_counts = Counter(tag for t in tests for tag in t.tags)
    if tag_counts:
        breakdown = ", ".join(f"{count} tagged {tag}" for tag, count in sorted(tag_counts.items()))
        line += f" ({breakdown})"

    return line
