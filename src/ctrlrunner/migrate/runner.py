"""
Drives the migration of a set of paths: scan (pass 1), transform each
file (pass 2), fix up imports (pass 3), then either print diffs
(dry-run, the default) or write the files in place (--write).
"""

import difflib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .report import FileReport, MigrationReport
from .scanner import ProjectIndex, scan

if TYPE_CHECKING:
    # Always resolved for the type checker, which has no notion of the
    # runtime "libcst may not be installed" fallback below.
    import libcst as cst
    from libcst.metadata import MetadataWrapper
else:
    try:
        import libcst as cst
        from libcst.metadata import MetadataWrapper
    except ImportError:  # pragma: no cover
        cst = None
        MetadataWrapper = None


def _require_libcst():
    if cst is None:
        raise SystemExit(
            "ctrlrunner.migrate requires libcst (needed only for migration, "
            "never at test runtime):\n\n    pip install libcst\n"
        )


# ---------- import fixup (pass 3) -------------------------------------------


def _is_docstring(stmt) -> bool:
    return (
        isinstance(stmt, cst.SimpleStatementLine)
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], cst.Expr)
        and isinstance(stmt.body[0].value, (cst.SimpleString, cst.ConcatenatedString))
    )


def _is_import_line(stmt) -> bool:
    return isinstance(stmt, cst.SimpleStatementLine) and all(
        isinstance(s, (cst.Import, cst.ImportFrom)) for s in stmt.body
    )


def _import_module_name(stmt) -> str | None:
    """Module name for single-import lines ('pytest', 'ctrlrunner', ...)."""
    if not (isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1):
        return None
    imp = stmt.body[0]
    if isinstance(imp, cst.Import) and len(imp.names) == 1:
        node, parts = imp.names[0].name, []
        while isinstance(node, cst.Attribute):
            parts.append(node.attr.value)
            node = node.value
        if isinstance(node, cst.Name):
            parts.append(node.value)
        return ".".join(reversed(parts))
    if isinstance(imp, cst.ImportFrom) and imp.module is not None:
        node, parts = imp.module, []
        while isinstance(node, cst.Attribute):
            parts.append(node.attr.value)
            node = node.value
        if isinstance(node, cst.Name):
            parts.append(node.value)
        return ".".join(reversed(parts))
    return None


def _name_used(name: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


def _alias_local_name(alias: "cst.ImportAlias") -> str:
    """The local (possibly aliased) name bound by a `from x import ...`
    alias -- always a plain Name for the import lists this module deals
    with (never the tuple/list unpacking targets AsName also allows for
    `with`/`except` clauses)."""
    target = alias.asname.name if alias.asname else alias.name
    assert isinstance(target, cst.Name)
    return target.value


def fix_imports(
    module: "cst.Module", needed: set[str], playwright: set[str], report: FileReport
) -> "cst.Module":
    body = list(module.body)

    # --- text of everything except import lines, to test remaining usage
    non_import_code = "".join(
        cst.Module(body=[stmt]).code for stmt in body if not _is_import_line(stmt)
    )

    new_body, removed, kept_pytest = [], 0, False
    for stmt in body:
        module_name = _import_module_name(stmt)
        if module_name != "pytest" or not _is_import_line(stmt):
            new_body.append(stmt)
            continue
        assert isinstance(stmt, cst.SimpleStatementLine)
        imp = stmt.body[0]
        assert isinstance(imp, (cst.Import, cst.ImportFrom))
        if isinstance(imp, cst.Import):
            if imp.names[0].asname:
                asname_target = imp.names[0].asname.name
                assert isinstance(asname_target, cst.Name)
                alias_name = asname_target.value
            else:
                alias_name = "pytest"
            if _name_used(alias_name, non_import_code):
                new_body.append(stmt)
                kept_pytest = True
            else:
                removed += 1
        elif isinstance(imp.names, cst.ImportStar):
            # "from pytest import *" can't be rewritten mechanically --
            # every name in the file might secretly be pytest's. Keep the
            # line and flag it for a human instead of crashing the whole
            # migration run (this used to be a bare assert, and
            # migrate_paths only catches parse/recursion errors).
            new_body.append(stmt)
            kept_pytest = True
        else:  # from pytest import a, b as c
            survivors = []
            for alias in imp.names:
                local = _alias_local_name(alias)
                # Names re-imported from ctrlrunner shadow-replace the
                # pytest ones; other names survive only if still used.
                if local in needed:
                    continue
                if _name_used(local, non_import_code):
                    survivors.append(alias)
            if survivors:
                survivors[-1] = survivors[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
                new_body.append(stmt.with_changes(body=[imp.with_changes(names=survivors)]))
                kept_pytest = True
            else:
                removed += 1
    if removed:
        report.add("imports", removed)
    if kept_pytest:
        report.todo(
            0,
            "file still imports pytest -- remaining usages are "
            "marked with TODO(ctrlrunner-migrate) above",
        )
    body = new_body

    # --- merge into an existing `from ctrlrunner import ...` if present
    still_needed = set(needed)
    for i, stmt in enumerate(body):
        if (
            _import_module_name(stmt) == "ctrlrunner"
            and _is_import_line(stmt)
            and isinstance(stmt.body[0], cst.ImportFrom)
            and not isinstance(stmt.body[0].names, cst.ImportStar)
        ):
            imp = stmt.body[0]
            present = {a.name.value for a in imp.names}
            add = sorted(still_needed - present)
            if add:
                names = list(imp.names)
                names[-1] = names[-1].with_changes(
                    comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
                )
                names += [cst.ImportAlias(name=cst.Name(n)) for n in add]
                for j in range(len(names) - 1):
                    if names[j].comma == cst.MaybeSentinel.DEFAULT:
                        names[j] = names[j].with_changes(
                            comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
                        )
                body[i] = stmt.with_changes(body=[imp.with_changes(names=names)])
                report.add("imports")
            still_needed.clear()
            break

    # --- insert brand-new import lines after the header import block
    inserts = []
    if still_needed:
        inserts.append(f"from ctrlrunner import {', '.join(sorted(still_needed))}\n")
    existing_code = cst.Module(body=body).code
    playwright_missing = sorted(
        n
        for n in playwright
        if not re.search(
            rf"from\s+ctrlrunner\.playwright\.playwright_fixtures\s+import\s+[^\n]*\b{n}\b",
            existing_code,
        )
    )
    if playwright_missing:
        inserts.append(
            "from ctrlrunner.playwright.playwright_fixtures import "
            + ", ".join(playwright_missing)
            + "\n"
        )
    if inserts:
        idx = 0
        if body and _is_docstring(body[0]):
            idx = 1
        while idx < len(body) and _is_import_line(body[idx]):
            idx += 1
        parsed = [cst.parse_statement(src) for src in inserts]
        body = body[:idx] + parsed + body[idx:]
        report.add("imports", len(inserts))

    return module.with_changes(body=body)


# ---------- per-file + whole-run drivers -------------------------------------


def migrate_source(
    source: str,
    path: Path,
    index: ProjectIndex,
    report: FileReport,
    case_id_marker: str = "test_case_id",
) -> str:
    from .transformer import MigrationTransformer

    is_conftest = path.name == "conftest.py"
    is_test_file = (
        path.name.startswith("test_") or path.stem.endswith("_test")
    ) and not is_conftest
    wrapper = MetadataWrapper(cst.parse_module(source))
    transformer = MigrationTransformer(
        index,
        report,
        is_test_file=is_test_file,
        is_conftest=is_conftest,
        case_id_marker=case_id_marker,
    )
    new_module = wrapper.visit(transformer)
    if transformer.needed_imports or transformer.playwright_imports or new_module.code != source:
        new_module = fix_imports(
            new_module, transformer.needed_imports, transformer.playwright_imports, report
        )
    return new_module.code


def migrate_paths(
    paths,
    write: bool = False,
    index: ProjectIndex | None = None,
    case_id_marker: str = "test_case_id",
    migrate_config_files: bool = True,
) -> tuple[MigrationReport, list[tuple[Path, str, str]]]:
    """Returns (report, [(path, old_source, new_source), ...] for changed
    files). Writes in place only when write=True."""
    _require_libcst()
    index = index or scan(paths)
    report = MigrationReport()
    changes = []
    for path in index.files:
        file_report = FileReport(path=path)
        report.files.append(file_report)
        try:
            source = path.read_text(encoding="utf-8")
            new_source = migrate_source(
                source, path, index, file_report, case_id_marker=case_id_marker
            )
        except cst.ParserSyntaxError as exc:
            file_report.error = f"parse error: {exc.message}"
            continue
        except RecursionError:
            file_report.error = "file too deeply nested to transform"
            continue
        if new_source != source:
            file_report.changed = True
            changes.append((path, source, new_source))
            if write:
                path.write_text(new_source, encoding="utf-8")

    if migrate_config_files:
        from .config_migrator import migrate_config

        config = migrate_config(paths, case_id_marker=case_id_marker)
        if config is not None:
            config_report = FileReport(path=config.target)
            report.files.append(config_report)
            if config.skipped_reason:
                config_report.todo(0, config.skipped_reason)
            elif config.text is not None:
                config_report.changed = True
                config_report.add("config", config.mapped)
                for note in config.notes:
                    config_report.todo(0, note)
                changes.append((config.target, "", config.text))
                if write:
                    config.target.write_text(config.text, encoding="utf-8")
    return report, changes


def render_diffs(changes) -> str:
    out = []
    for path, old, new in changes:
        out.extend(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=str(path),
                tofile=f"{path} (migrated)",
            )
        )
    return "".join(out)
