"""Font catalogue — the source of truth for ``BrandSettings.font_family``.

The catalogue lists every font the renderer can serve to ffmpeg
``drawtext``: a stable canonical ``family`` name (persisted verbatim
on ``BrandSettings.font_family``), a UI-facing ``display_name`` and the
on-disk paths for the regular and bold weights. The paths are
**workspace-relative** so the same descriptor works in tests, dev and
production — ``modules.rendering.infrastructure.runtime.resolve_font_path``
absolutises them at render time against the repository root.

Layer rule: this module lives in ``modules/configuration/domain`` and
has zero infrastructure or application imports. ``font_catalog.resolve``
is a pure helper consumed both by the ``GET /v1/admin/fonts`` use case
and by the reels ingest pipeline; transports decide how to surface a
``ValueError`` (the brand payload validator turns it into a 422
``UNKNOWN_FONT_FAMILY``).

Feature 28: the MVP catalogue ships seven families backed by Google OFL
fonts already present under ``assets/fonts/``:

* ``Inter`` — original static cuts under ``assets/fonts/Inter/static/``.
* ``Manrope`` — variable TTF (the ``Bold.ttf`` file is a copy of
  ``Regular.ttf`` because Google Fonts upstream only publishes the
  variable cut; the duplicate keeps the renderer contract intact and
  ffmpeg ``drawtext`` resolves a default weight on read).
* ``Plus Jakarta Sans`` — same variable-cut pattern as Manrope.
* ``Montserrat`` — same variable-cut pattern.
* ``Poppins`` — true static ``Regular`` / ``Bold`` TTFs from upstream.
* ``Roboto`` — variable cut (width + weight axes), same duplication
  pattern as Manrope.
* ``Barlow Semi Condensed`` — true static ``Regular`` / ``Bold`` TTFs
  fetched from Google Fonts' CSS2 API (same upstream pattern as
  Poppins).

The ``available()`` helper on each descriptor returns ``False`` when the
TTF is missing from disk; the fonts router surfaces that flag so a
broken deploy can be diagnosed from the admin console without reading
the worker logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FontDescriptor:
    """One font family available to the brand-settings selector."""

    family: str
    """Canonical name persisted on ``BrandSettings.font_family``.

    Used verbatim by the renderer + frontend dropdown. The value is
    case-sensitive: the validator on the brand payload matches against
    this exact string.
    """

    display_name: str
    """Label shown by the frontend dropdown (today same as ``family``)."""

    regular_path: Path
    """Workspace-relative path to the regular-weight TTF.

    Resolved against the repository root by
    ``modules.rendering.infrastructure.runtime.resolve_font_path`` at
    render time.
    """

    bold_path: Path
    """Workspace-relative path to the bold-weight TTF.

    For variable-cut fonts this points at the same TTF as
    ``regular_path``: the renderer accepts duplicate weights without
    failing and ffmpeg ``drawtext`` falls back to the file's default
    weight when the requested cut is missing.
    """

    def available(self, *, workspace_dir: Path | None = None) -> bool:
        """Return whether both TTFs exist on disk.

        ``workspace_dir`` is the repository root used to absolutise the
        workspace-relative paths in the catalogue. When omitted the
        check resolves the paths verbatim, which is sufficient for the
        admin ``GET /v1/admin/fonts`` endpoint (the API process runs
        with the repository as CWD).
        """
        regular = (
            (workspace_dir / self.regular_path)
            if workspace_dir is not None and not self.regular_path.is_absolute()
            else self.regular_path
        )
        bold = (
            (workspace_dir / self.bold_path)
            if workspace_dir is not None and not self.bold_path.is_absolute()
            else self.bold_path
        )
        return regular.is_file() and bold.is_file()


AVAILABLE_FONTS: tuple[FontDescriptor, ...] = (
    FontDescriptor(
        family="Inter",
        display_name="Inter",
        regular_path=Path("assets/fonts/Inter/static/Inter_28pt-Regular.ttf"),
        bold_path=Path("assets/fonts/Inter/static/Inter_28pt-Bold.ttf"),
    ),
    FontDescriptor(
        family="Manrope",
        display_name="Manrope",
        regular_path=Path("assets/fonts/Manrope/Regular.ttf"),
        bold_path=Path("assets/fonts/Manrope/Bold.ttf"),
    ),
    FontDescriptor(
        family="Plus Jakarta Sans",
        display_name="Plus Jakarta Sans",
        regular_path=Path("assets/fonts/Plus_Jakarta_Sans/Regular.ttf"),
        bold_path=Path("assets/fonts/Plus_Jakarta_Sans/Bold.ttf"),
    ),
    FontDescriptor(
        family="Montserrat",
        display_name="Montserrat",
        regular_path=Path("assets/fonts/Montserrat/Regular.ttf"),
        bold_path=Path("assets/fonts/Montserrat/Bold.ttf"),
    ),
    FontDescriptor(
        family="Poppins",
        display_name="Poppins",
        regular_path=Path("assets/fonts/Poppins/Regular.ttf"),
        bold_path=Path("assets/fonts/Poppins/Bold.ttf"),
    ),
    FontDescriptor(
        family="Roboto",
        display_name="Roboto",
        regular_path=Path("assets/fonts/Roboto/Regular.ttf"),
        bold_path=Path("assets/fonts/Roboto/Bold.ttf"),
    ),
    FontDescriptor(
        family="Barlow Semi Condensed",
        display_name="Barlow Semi Condensed",
        regular_path=Path("assets/fonts/Barlow_Semi_Condensed/Regular.ttf"),
        bold_path=Path("assets/fonts/Barlow_Semi_Condensed/Bold.ttf"),
    ),
)


ALLOWED_FONT_FAMILIES: frozenset[str] = frozenset(
    descriptor.family for descriptor in AVAILABLE_FONTS
)
"""Set of canonical family names accepted by the brand payload.

Surfaced to the user in the 422 ``UNKNOWN_FONT_FAMILY`` payload as
``details.allowed_families`` so the frontend can render a clear hint.
"""


DEFAULT_FONT_FAMILY: str = "Inter"
"""Family used by the renderer when ``BrandSettings.font_family`` is null.

Inter is the historical default — its static TTFs are the bundled
fallback when an agency never edits ``/brand`` (or explicitly clears the
field by sending ``font_family: null``).
"""


def resolve_weighted(family: str | None, weight: str | None) -> tuple[Path, Path]:
    """Return ``(primary_path, bold_path)`` for a weighted subtitle drawtext.

    Feature 31: the per-agency subtitle settings let the user choose a
    weight per render (``500`` / ``600`` / ``700`` / ``800``). The
    renderer can only feed a single TTF to ffmpeg ``drawtext``, so this
    helper picks the right cut from the catalogue:

    * ``weight >= 700`` → ``bold_path`` (heavy weights cluster around the
      bold cut; ffmpeg ``drawtext`` does not synthesise stroke).
    * ``weight < 700`` → ``regular_path``.

    The returned tuple keeps both paths so callers that want to mix
    bold / regular within the same overlay (e.g. caption + subtitle)
    can avoid a second ``resolve_weighted`` call. Invalid / empty
    ``weight`` strings are treated as ``500`` (regular).
    """
    descriptor = resolve(family)
    raw = (weight or "").strip()
    try:
        weight_int = int(raw) if raw else 500
    except ValueError:
        weight_int = 500
    primary = descriptor.bold_path if weight_int >= 700 else descriptor.regular_path
    return primary, descriptor.bold_path


def resolve(family: str | None) -> FontDescriptor:
    """Return the descriptor for ``family`` or the default when null.

    Empty/whitespace-only strings are treated as null so ingestion does
    not have to special-case them downstream. The lookup is
    case-sensitive: callers should pass the canonical name from
    :data:`AVAILABLE_FONTS`.

    Raises:
        ValueError: when ``family`` is non-empty but not present in the
            catalogue. Transports decide the HTTP status (the brand
            payload validator turns it into 422 ``UNKNOWN_FONT_FAMILY``;
            the ingest pipeline falls back to the default with a
            warning).
    """
    if family is None:
        return _by_family(DEFAULT_FONT_FAMILY)
    stripped = family.strip()
    if not stripped:
        return _by_family(DEFAULT_FONT_FAMILY)
    return _by_family(stripped)


def _by_family(family: str) -> FontDescriptor:
    for descriptor in AVAILABLE_FONTS:
        if descriptor.family == family:
            return descriptor
    raise ValueError(f"Unknown font family: {family!r}")


__all__ = [
    "ALLOWED_FONT_FAMILIES",
    "AVAILABLE_FONTS",
    "DEFAULT_FONT_FAMILY",
    "FontDescriptor",
    "resolve",
    "resolve_weighted",
]
