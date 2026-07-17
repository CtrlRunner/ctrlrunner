from importlib.metadata import PackageNotFoundError, version

from .core.annotations import fail, fixme, record_suite_property, skip, slow
from .core.context_info import record_property
from .core.options import get_option, get_options
from .core.registry import fixture, param, parametrize, test, test_class
from .core.steps import step
from .playwright.playwright_actions import auto_step

try:
    __version__ = version("ctrlrunner")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = [
    "__version__",
    "fixture",
    "test",
    "test_class",
    "parametrize",
    "param",
    "step",
    "skip",
    "fail",
    "fixme",
    "slow",
    "auto_step",
    "record_property",
    "record_suite_property",
    "get_option",
    "get_options",
]
