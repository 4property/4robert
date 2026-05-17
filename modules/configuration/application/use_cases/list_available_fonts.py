"""Use case: list the catalogue of fonts exposed to the brand selector.

Feature 28: the frontend `/brand` page consumed a hardcoded dropdown
with five families, only one of which (Inter) had a TTF in the
backend's ``assets/fonts/``. This use case is the canonical reader of
the font catalogue defined in
:mod:`modules.configuration.domain.font_catalog`, served by the
``GET /v1/admin/fonts`` admin endpoint.

Pure-compute, no DB access, no UoW: the catalogue is in-memory module
state. The use case exists as a thin wrapper so the transport layer
doesn't import the domain module directly — the indirection mirrors
the rest of the configuration use cases and keeps the catalogue
discoverable from the use-case index.
"""

from __future__ import annotations

from modules.configuration.domain import font_catalog
from modules.configuration.domain.font_catalog import FontDescriptor


class ListAvailableFontsUseCase:
    """Return the immutable tuple of catalogue entries."""

    def execute(self) -> tuple[FontDescriptor, ...]:
        return font_catalog.AVAILABLE_FONTS


__all__ = ["ListAvailableFontsUseCase"]
