"""
Optional tag registry (ctrlrunner.toml `registered_tags`) -- catches
typos in @test(tags=...) before they cause a test to silently not
match a `--tag` filter, without requiring every tag to be registered
up front (opt-in; warning-mode by default even once enabled).

Absent `registered_tags` entirely: zero behavior change, zero
validation, matches today exactly.
"""

import sys
from collections.abc import Iterable
from dataclasses import dataclass


class TagValidationError(Exception):
    """Raised only in strict mode, only from the CLI run path -- see
    Orchestrator.run(). Never raised by RunController (UI Mode always
    treats unregistered tags as a warning; see its module docstring)."""


@dataclass
class TagRegistry:
    entries: list[str]
    strict: bool = False

    def is_registered(self, tag: str) -> bool:
        for entry in self.entries:
            # Only the documented ":*"/"_*" suffix forms are prefix
            # patterns -- a bare trailing "*" on any other entry
            # (e.g. "footer*") used to match every tag starting with
            # "footer", far beyond the documented syntax, and a lone
            # "*" entry (however it got constructed) would match
            # everything and silently disable validation entirely.
            if entry.endswith(":*") or entry.endswith("_*"):
                prefix = entry[:-1]
                if prefix and tag.startswith(prefix):
                    return True
            elif entry == tag:
                return True
        return False

    def unregistered(self, tags: Iterable[str]) -> set[str]:
        return {t for t in tags if not self.is_registered(t)}


def load_tag_registry(config: dict, strict_override: bool | None = None) -> TagRegistry | None:
    """Returns None (no validation at all) if `registered_tags` isn't in
    config -- the "absent = no behavior change" default. `strict_override`
    lets a CLI flag (--strict-tags) win over the config file's
    `strict_tags` for a single run, same CLI > config precedence as
    everything else."""
    entries = config.get("registered_tags")
    if entries is None:
        return None
    if "*" in entries:
        raise ValueError(
            "registered_tags contains a bare '*' entry, which would match every "
            "tag and silently disable validation entirely. Use a specific prefix "
            "pattern instead (e.g. 'team:*'), or remove registered_tags/strict_tags "
            "if you don't want validation at all."
        )
    strict = config.get("strict_tags", False) if strict_override is None else strict_override
    return TagRegistry(entries=list(entries), strict=bool(strict))


def validate_tags(tests, registry: TagRegistry) -> list[str]:
    """Returns the sorted list of unregistered tags found across every
    collected test (not just a selected subset -- the point is to catch
    typos anywhere in the suite, regardless of which tests a particular
    --tag/--case-id happens to select this run)."""
    all_tags: set[str] = set()
    for t in tests:
        all_tags.update(t.tags)
    return sorted(registry.unregistered(all_tags))


def format_unregistered_tags_warning(unregistered: list[str]) -> str:
    """Single shared message format for the 'some tags aren't in
    registered_tags' warning/error, used at every call site
    (Orchestrator.run(), cli.py's --list branch, RunController) so the
    three previously-duplicated copies can't silently drift from each
    other again."""
    return f"{len(unregistered)} tag(s) not in registered_tags: {', '.join(sorted(unregistered))}"


def warn_unregistered_cli_tags(cli_tags: Iterable[str], registry: TagRegistry | None) -> None:
    """Separate, always-warning-only check (never blocking, even in
    strict mode) for the literal --tag values a person passed on the
    command line -- a one-off `--tag hotfix-123` shouldn't require a
    config change, but a likely typo is still worth flagging."""
    if registry is None:
        return
    for tag in cli_tags:
        if not registry.is_registered(tag):
            print(f"Warning: --tag '{tag}' is not in registered_tags (typo?)", file=sys.stderr)
