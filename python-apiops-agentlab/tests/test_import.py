"""Import baseline tests for the Python AgentLab package."""

import inspect

import app
import app.main


def test_app_package_and_async_module_import() -> None:
    """The formal package imports and exposes a typed async boundary."""
    assert app.__name__ == "app"
    assert app.main.__name__ == "app.main"
    assert inspect.iscoroutinefunction(app.main.main)
