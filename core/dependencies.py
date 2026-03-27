from __future__ import annotations

import importlib
from types import ModuleType

from core.errors import DependencyNotInstalledError


def require_dependency(
    module_name: str,
    *,
    package_name: str | None = None,
    display_name: str | None = None,
    feature: str | None = None,
) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_module_name = exc.name or module_name
        missing_package_name = package_name if missing_module_name == module_name else None
        missing_display_name = display_name if missing_module_name == module_name else None
        raise DependencyNotInstalledError(
            module_name=missing_module_name,
            package_name=missing_package_name,
            display_name=missing_display_name,
            feature=feature,
        ) from exc


__all__ = ["require_dependency"]
