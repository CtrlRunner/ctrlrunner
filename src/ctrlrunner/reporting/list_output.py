"""
--list output formatting. A pure view over already-selected TestItems: never a
separate discovery path, just a different thing to do with the exact
same discover_and_import() + select_tests() pipeline every real run
uses (see cli.py's --list branch).
"""

import json as json_module

from ..core.registry import TestItem

ALL_FIELDS = [
    "id",
    "caseId",
    "tags",
    "timeout",
    "retries",
    "className",
    "properties",
    "project",
    "riskFlag",
]
DEFAULT_FIELDS = ["id", "caseId", "tags"]


def _row(item: TestItem) -> dict:
    return {
        "id": item.id,
        "caseId": item.case_id,
        "tags": sorted(item.tags),
        "timeout": item.timeout,
        "retries": item.retries,
        "className": item.class_name,
        "properties": item.properties,
        "project": item.project,
        "riskFlag": item.risk_flag,
    }


def _format_scalar(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(value)
    if isinstance(value, dict):
        return ",".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def format_list(tests: list[TestItem], fmt: str, fields: list[str] | None = None) -> str:
    """fmt: "text" | "json" | "md". `fields` only affects text/md --
    json always includes every field (a consumer can filter client-side
    trivially, and the point of --list json is a complete machine-
    readable snapshot).

    Raises ValueError for an unknown format or an unknown field name,
    rather than silently ignoring a typo -- consistent with this
    project's "fail fast, clear error" precedent elsewhere (decorator
    ordering, config validation).
    """
    if fmt not in ("text", "json", "md"):
        raise ValueError(f"Unknown --list format '{fmt}', expected 'text', 'json', or 'md'")

    selected_fields = fields or DEFAULT_FIELDS
    unknown = [f for f in selected_fields if f not in ALL_FIELDS]
    if unknown:
        raise ValueError(
            f"Unknown --list-fields: {', '.join(unknown)}. Valid fields: {', '.join(ALL_FIELDS)}"
        )

    rows = [_row(t) for t in tests]

    if fmt == "json":
        return json_module.dumps({"tests": rows}, indent=2)

    if fmt == "md":
        header = "| " + " | ".join(selected_fields) + " |"
        sep = "| " + " | ".join("---" for _ in selected_fields) + " |"
        lines = [header, sep]
        for row in rows:
            cells = [_format_scalar(row[f]) for f in selected_fields]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    # text: one line per test, "field=value" pairs after the bare id --
    # labeled rather than positional so arbitrary --list-fields
    # combinations stay self-describing without special-casing any one
    # field's presentation.
    lines = []
    for row in rows:
        parts = [row["id"]] if "id" in selected_fields else []
        for f in selected_fields:
            if f == "id":
                continue
            value = _format_scalar(row[f])
            if value:
                parts.append(f"{f}={value}")
        lines.append("  ".join(parts))
    return "\n".join(lines)
