"""
A generic grouping strategy system for the HTML report / UI Mode, replacing the hardcoded
`test_id.split("::")[0]` that used to live independently in both
html_report.py's and ui_frontend.py's JS (a duplication risk: the two
could silently drift in how they parsed test_id).

"module" stays the always-available default dimension when no
`[grouping]` config exists at all -- zero config, zero behavior change,
identical to the old hardcoded split. A `[grouping]` section otherwise
uses whatever dimensions are listed, but "module" is always force-added
(prepended, not duplicated) if the user's list omits it -- module is
"always present ... for backward compatibility" (every existing
consumer, including the HTML report's default grouped view, relies on
it), so an incomplete custom dimension list must not silently drop it.
The one deliberate exception: an explicitly PRESENT but empty
`dimensions = []` is user intent gone wrong, not "omitted module" --
it still raises (see below) rather than being "fixed" by auto-adding
module.
"""

from dataclasses import dataclass, field
from pathlib import Path

from ..core.registry import TestItem

UNGROUPED = "ungrouped"

_VALID_STRATEGIES = {"module", "path", "tag_prefix", "property"}


@dataclass
class GroupingDimension:
    name: str
    strategy: str  # "module" | "path" | "tag_prefix" | "property"
    options: dict = field(default_factory=dict)


DEFAULT_DIMENSIONS = [GroupingDimension(name="module", strategy="module")]


def load_grouping_dimensions(config: dict) -> list[GroupingDimension]:
    """Returns DEFAULT_DIMENSIONS (just "module") if `[grouping]` is
    absent from config entirely -- the zero-config, zero-behavior-change
    default. Raises ValueError immediately (not per-test, later) for an
    unknown strategy or a strategy missing its required option, so a
    config typo fails fast at startup rather than silently mis-grouping
    every test in the run. An explicitly PRESENT but empty [grouping]
    table (no 'dimensions' key, or an empty one) is treated as user
    intent gone wrong, not as "absent" -- it raises too, rather than
    silently falling back to the default the user apparently didn't want."""
    grouping_config = config.get("grouping")
    if grouping_config is None:
        return DEFAULT_DIMENSIONS

    raw_dimensions = grouping_config.get("dimensions", [])
    dimensions = []
    for raw in raw_dimensions:
        name = raw.get("name")
        strategy = raw.get("strategy")
        if not name or not strategy:
            raise ValueError(
                f"Invalid [grouping] dimension {raw!r}: both 'name' and 'strategy' are required."
            )
        if strategy not in _VALID_STRATEGIES:
            raise ValueError(
                f"[grouping] dimension '{name}' has unknown strategy '{strategy}'. "
                f"Valid strategies: {', '.join(sorted(_VALID_STRATEGIES))}."
            )
        options = {k: v for k, v in raw.items() if k not in ("name", "strategy")}
        if strategy == "path" and "depth" not in options:
            raise ValueError(
                f"[grouping] dimension '{name}' uses strategy 'path' but is missing 'depth'."
            )
        if strategy == "path" and "depth" in options:
            depth_value = options["depth"]
            # depth was presence-checked but not type-checked --
            # `depth = "2"` from TOML would previously sail through here
            # and fail confusingly later inside _group_by_path's
            # min/max arithmetic instead of failing clearly at load
            # time. bool is an int subclass in Python but is never a
            # sensible depth, so it's explicitly rejected too.
            if isinstance(depth_value, bool) or not isinstance(depth_value, int):
                raise ValueError(
                    f"[grouping] dimension '{name}' has 'depth' of type "
                    f"{type(depth_value).__name__}; it must be an int."
                )
        if strategy == "tag_prefix" and "prefix" not in options:
            raise ValueError(
                f"[grouping] dimension '{name}' uses strategy 'tag_prefix' but is missing 'prefix'."
            )
        if strategy == "property" and "key" not in options:
            raise ValueError(
                f"[grouping] dimension '{name}' uses strategy 'property' but is missing 'key'."
            )
        dimensions.append(GroupingDimension(name=name, strategy=strategy, options=options))

    if not dimensions:
        raise ValueError("[grouping] section present but 'dimensions' is empty.")

    if not any(d.name == "module" for d in dimensions):
        dimensions.insert(0, GroupingDimension(name="module", strategy="module"))
    return dimensions


def _group_by_module(item: TestItem) -> str:
    return item.id.partition("::")[0]


def _group_by_path(item: TestItem, depth: int, root: str | None) -> str:
    if item.source_path is None:
        return UNGROUPED
    try:
        root_path = Path(root).resolve() if root else None
        source = item.source_path.resolve()
        rel = source.relative_to(root_path) if root_path else source
    except (ValueError, OSError):
        return item.source_path.parent.name or UNGROUPED

    dir_parts = rel.parts[:-1]  # drop the filename itself
    if not dir_parts:
        return UNGROUPED  # file sits directly in the root, no subdirectory segment
    idx = min(max(depth, 0), len(dir_parts) - 1)
    return dir_parts[idx]


def _group_by_tag_prefix(item: TestItem, prefix: str) -> str:
    matches = sorted(tag[len(prefix) :] for tag in item.tags if tag.startswith(prefix))
    if not matches:
        return UNGROUPED
    return "+".join(matches)  # deterministic, doesn't silently drop a match if >1 apply


def _group_by_property(item: TestItem, key: str) -> str:
    return item.properties.get(key, UNGROUPED)


def compute_groups(
    item: TestItem, dimensions: list[GroupingDimension], root: str | None = None
) -> dict[str, str]:
    groups = {}
    for dim in dimensions:
        if dim.strategy == "module":
            groups[dim.name] = _group_by_module(item)
        elif dim.strategy == "path":
            groups[dim.name] = _group_by_path(item, dim.options["depth"], root)
        elif dim.strategy == "tag_prefix":
            groups[dim.name] = _group_by_tag_prefix(item, dim.options["prefix"])
        elif dim.strategy == "property":
            groups[dim.name] = _group_by_property(item, dim.options["key"])
    return groups
