"""
ctrlrunner_addoption -- the pytest_addoption equivalent.

A conftest.py may define:

    def ctrlrunner_addoption(parser):
        parser.addoption("--env", default="qa",
                         choices=["qa", "staging", "prod"],
                         help="target environment")

The CLI imports every conftest.py that applies to the run's root
BEFORE building its final argument parser (two-phase parse -- see
cli.py), collects these declarations through the OptionParser shim
below, and materializes them as real, typed argparse flags: they
appear in --help, validate choices, coerce types, and their resolved
values (CLI flag > [ctrlrunner.options] in ctrlrunner.toml > declared
default) are seeded into core.options for `get_option(...)` reads in
every process.

The shim accepts pytest's `parser.addoption(...)` signature, which is
argparse-compatible -- migrated pytest_addoption bodies work unchanged
after the function is renamed to ctrlrunner_addoption (the migration
tool does that rename automatically).

The same conftest import pass also collects two sibling hooks, the
pytest_configure/pytest_sessionfinish equivalents -- plain functions,
not declarations, so collect_declarations() just gathers the callables
here; cli.py invokes them once each around the run with pytest-shaped
arguments (core/hookcompat.py's Config/Session shims -- docs/hooks.md
has the full contract):

    def ctrlrunner_configure(config):
        ...  # once, main process, before the run; config.getoption() works

    def ctrlrunner_sessionfinish(session, exitstatus):
        ...  # once, main process, after the run; session.results/.duration
"""

import argparse
import sys
from dataclasses import dataclass
from typing import Any


class AddoptionError(ValueError):
    """A bad ctrlrunner_addoption declaration (duplicate flag, name
    colliding with a built-in ctrlrunner flag, invalid toml value for a
    declared choices= option, ...)."""


# The conftest hooks that run in the MAIN process, collected by
# collect_declarations() and invoked from cli.py around the run. The
# per-test ctrlrunner_runtest_* hooks are worker-side (worker.py); the
# collection-phase hooks are orchestrator-side (orchestrator.py).
MAIN_PROCESS_HOOKS = (
    "ctrlrunner_configure",
    "ctrlrunner_sessionstart",
    "ctrlrunner_sessionfinish",
    "ctrlrunner_unconfigure",
    "ctrlrunner_report_header",
    "ctrlrunner_terminal_summary",
    "ctrlrunner_report_teststatus",
)


@dataclass
class _Declaration:
    names: tuple  # ("--env",) or ("-e", "--env")
    # action/type/choices/help/dest/... -- everything except default.
    # Deliberately Any-valued: these become **kwargs passed straight
    # into argparse.add_argument, whose parameters have heterogeneous
    # types (action: str, required: bool, type: Callable, ...) that a
    # single dict type can't express -- Any tells the type checker this
    # dict is intentionally dynamic, matching argparse's own stubs
    # requiring literal **kwargs at each call site.
    kwargs: dict[str, Any]
    default: object
    source: str  # declaring conftest.py path, for error messages
    dest: str | None = None  # filled in by apply_to()


class OptionParser:
    """The `parser` object handed to ctrlrunner_addoption(parser)."""

    def __init__(self):
        self._declarations: list[_Declaration] = []
        self._by_name: dict[str, str] = {}  # option string -> declaring conftest path
        self._source = "<unknown>"
        # The main-process conftest hooks -- collected in the same
        # conftest import pass as ctrlrunner_addoption (see
        # collect_declarations below), in conftest discovery order
        # (shallowest-first). Not declarations, just plain callables.
        self.hooks: dict[str, list] = {name: [] for name in MAIN_PROCESS_HOOKS}

    @property
    def configure_hooks(self) -> list:
        return self.hooks["ctrlrunner_configure"]

    @property
    def sessionfinish_hooks(self) -> list:
        return self.hooks["ctrlrunner_sessionfinish"]

    # ---- declaration API (what conftest code calls) -------------------

    def addoption(self, *names, **kwargs):
        if not names or not all(isinstance(n, str) and n.startswith("-") for n in names):
            raise AddoptionError(
                f"{self._source}: ctrlrunner_addoption option names must be flag "
                f"strings starting with '-', got {names!r}"
            )
        for n in names:
            if n in self._by_name:
                # pytest also errors on a flag declared twice -- name
                # both declaration sites so the fix is obvious.
                raise AddoptionError(
                    f"option {n!r} declared twice: in {self._by_name[n]} and {self._source}"
                )
            self._by_name[n] = self._source
        default = kwargs.pop("default", None)
        action = kwargs.get("action")
        if default is None and action == "store_true":
            default = False
        elif default is None and action == "store_false":
            default = True
        self._declarations.append(_Declaration(tuple(names), dict(kwargs), default, self._source))

    def getgroup(self, name, description="", after=None):
        # Minimal proxy: pytest conftests commonly do
        # `group = parser.getgroup("myproj"); group.addoption(...)` --
        # declarations just land in the same single bucket.
        return self

    def addini(self, name, help="", type=None, default=None):
        print(
            f"ctrlrunner: warning: {self._source}: parser.addini({name!r}) is not "
            f"supported -- put the value in [ctrlrunner.options] in ctrlrunner.toml "
            f"instead (get_option({name!r}) will read it).",
            file=sys.stderr,
        )

    # ---- CLI-side machinery ------------------------------------------

    def apply_to(self, parser: argparse.ArgumentParser) -> None:
        """Materializes every declaration onto the real parser, in a
        dedicated --help group. default=argparse.SUPPRESS is the
        explicit-presence detector: the namespace attribute exists only
        when the flag was actually typed, which is what lets resolve()
        implement CLI > toml > declared-default without argv sniffing.
        SUPPRESS breaks %(default)s in help strings, so the declared
        default is appended to the help text here instead."""
        builtin_dests = {a.dest for a in parser._actions}
        group = parser.add_argument_group("custom options (from ctrlrunner_addoption)")
        for d in self._declarations:
            help_text = d.kwargs.get("help") or ""
            if d.default is not None:
                help_text = f"{help_text} [default: {d.default}]".strip()
            # Explicit dict[str, Any] annotation: without it, the type
            # checker narrows this literal's value type to the union of
            # its individual entries' types (str for help/default) and
            # then rejects the whole dict against add_argument's
            # heterogeneous **kwargs (e.g. required: bool) -- Any tells
            # it this dict is deliberately dynamic, not that everything
            # in it happens to be str.
            kwargs: dict[str, Any] = {**d.kwargs, "help": help_text, "default": argparse.SUPPRESS}
            try:
                action = group.add_argument(*d.names, **kwargs)
            except argparse.ArgumentError as e:
                raise AddoptionError(f"{d.source}: {e}") from None
            if action.dest in builtin_dests:
                raise AddoptionError(
                    f"{d.source}: option {d.names[0]!r} resolves to dest "
                    f"{action.dest!r}, which collides with a built-in ctrlrunner flag"
                )
            d.dest = action.dest

    @staticmethod
    def _derive_dest(d: _Declaration) -> str:
        """argparse's dest rule, for use before apply_to has run:
        explicit dest= wins, else the first long option name, else the
        first name -- dashes stripped/underscored."""
        if d.kwargs.get("dest"):
            return d.kwargs["dest"]
        long_names = [n for n in d.names if n.startswith("--")]
        chosen = long_names[0] if long_names else d.names[0]
        return chosen.lstrip("-").replace("-", "_")

    def base_values(self, config_options: dict) -> dict:
        """declared defaults <- [ctrlrunner.options], WITHOUT any CLI
        layer (the base layer for multi-project merging). Undeclared
        toml keys pass through untouched -- usable via get_option with
        no declaration. Toml values keep their TOML types (type= only
        coerces CLI strings), but declared choices= are validated."""
        values = dict(config_options)
        for d in self._declarations:
            dest = d.dest or self._derive_dest(d)
            if dest in config_options:
                choices = d.kwargs.get("choices")
                if choices is not None and config_options[dest] not in choices:
                    raise AddoptionError(
                        f"[ctrlrunner.options] {dest} = {config_options[dest]!r}: "
                        f"not one of {list(choices)} (declared in {d.source})"
                    )
            else:
                values[dest] = d.default
        return values

    def cli_values(self, args: argparse.Namespace) -> dict:
        """Only the options explicitly typed on this command line
        (SUPPRESS => attribute present iff typed). The top layer of the
        precedence chain, kept separate so multi-project runs can apply
        it over each project's own options."""
        return {
            d.dest: getattr(args, d.dest)
            for d in self._declarations
            if d.dest is not None and hasattr(args, d.dest)
        }

    def resolve(self, config_options: dict, args: argparse.Namespace) -> dict:
        """CLI flag > [ctrlrunner.options] > declared default."""
        return {**self.base_values(config_options), **self.cli_values(args)}


def collect_declarations(roots: list[str], allow_unknown_hooks: bool = False) -> OptionParser:
    """Imports every conftest.py that applies to `roots` (ancestor walk
    to a .git boundary plus descendants -- the exact same discovery and
    sys.path setup the run itself performs later, via discover_conftests)
    and calls each module's ctrlrunner_addoption(parser), if defined.

    Conftest module level therefore runs in the main process BEFORE
    options are seeded -- get_option there returns defaults (documented
    caveat; workers never see it since they seed before importing).
    Import errors propagate to the caller for a clear CLI message."""
    # Lazy imports: config -> execution would otherwise be a cycle at
    # module import time (established pattern in this codebase).
    from pathlib import Path

    from ..execution.orchestrator import _dotted_module_name, discover_conftests
    from ..execution.worker import import_module_by_path

    shim = OptionParser()
    seen: set = set()
    for root in roots:
        root_path = Path(root).resolve()
        if not root_path.exists():
            # A bad/missing root fails later with today's exact error
            # message; "no custom options declared" is the right
            # behavior for this phase.
            continue
        if root_path.is_file():
            root_path = root_path.parent
        for p in discover_conftests(root):
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            key = import_module_by_path(p, _dotted_module_name(root_path, p))
            module = sys.modules[key]
            hook = getattr(module, "ctrlrunner_addoption", None)
            if hook is not None:
                from ..core.hookcompat import _PluginManager, bind_hook_args

                shim._source = str(p)
                # pytest's pytest_addoption(parser, pluginmanager) shape:
                # name-based binding keeps plain (parser) impls working.
                hook(**bind_hook_args(hook, {"parser": shim, "pluginmanager": _PluginManager()}))
            for hook_name in MAIN_PROCESS_HOOKS:
                fn = getattr(module, hook_name, None)
                if fn is not None:
                    shim.hooks[hook_name].append(fn)
            _check_unknown_hooks(module, p, allow_unknown_hooks)
    return shim


def _check_unknown_hooks(module, path, allow_unknown_hooks: bool) -> None:
    """Fail-loudly policy: a conftest function named like a hook
    ctrlrunner doesn't dispatch (any pytest_* name, or a ctrlrunner_*
    name outside the supported set) would otherwise be silently
    ignored -- the worst failure mode for migrated pytest projects.
    Abort with the per-hook recommendation; allow_unknown_hooks=true in
    ctrlrunner.toml downgrades to a stderr warning (for conftests
    serving both runners mid-migration)."""
    from ..core.hookcompat import SUPPORTED_HOOKS, hook_name_recommendation

    # Only functions DEFINED here count -- `from helpers import
    # pytest_x`-style re-exports still count, but imported modules'
    # attributes don't appear in vars(module) unless bound by name.
    offenders = [
        name
        for name, value in vars(module).items()
        if callable(value)
        and (name.startswith("pytest_") or name.startswith("ctrlrunner_"))
        and name not in SUPPORTED_HOOKS
    ]
    if not offenders:
        return
    lines = [f"  {name}: {hook_name_recommendation(name)}" for name in sorted(offenders)]
    message = f"{path}: unsupported hook function(s) in conftest.py:\n" + "\n".join(lines)
    if allow_unknown_hooks:
        print(f"Warning: {message}", file=sys.stderr)
        return
    raise AddoptionError(
        f"{message}\n(set allow_unknown_hooks = true in ctrlrunner.toml to "
        f"downgrade this to a warning during migration)"
    )
