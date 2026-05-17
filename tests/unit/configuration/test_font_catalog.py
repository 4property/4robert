"""Unit tests for ``modules.configuration.domain.font_catalog``."""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.configuration.domain import font_catalog


def test_available_fonts_contains_six_entries_in_canonical_order() -> None:
    families = [descriptor.family for descriptor in font_catalog.AVAILABLE_FONTS]
    assert families == [
        "Inter",
        "Manrope",
        "Plus Jakarta Sans",
        "Montserrat",
        "Poppins",
        "Roboto",
    ]
    assert len(font_catalog.AVAILABLE_FONTS) == 6


def test_allowed_font_families_matches_available_fonts() -> None:
    assert font_catalog.ALLOWED_FONT_FAMILIES == {
        descriptor.family for descriptor in font_catalog.AVAILABLE_FONTS
    }


def test_default_font_family_is_inter() -> None:
    assert font_catalog.DEFAULT_FONT_FAMILY == "Inter"


def test_resolve_inter_returns_static_paths() -> None:
    descriptor = font_catalog.resolve("Inter")
    assert descriptor.family == "Inter"
    assert descriptor.regular_path == Path(
        "assets/fonts/Inter/static/Inter_28pt-Regular.ttf"
    )
    assert descriptor.bold_path == Path(
        "assets/fonts/Inter/static/Inter_28pt-Bold.ttf"
    )


def test_resolve_manrope_returns_canonical_paths() -> None:
    descriptor = font_catalog.resolve("Manrope")
    assert descriptor.family == "Manrope"
    assert descriptor.regular_path == Path("assets/fonts/Manrope/Regular.ttf")
    assert descriptor.bold_path == Path("assets/fonts/Manrope/Bold.ttf")


@pytest.mark.parametrize("empty_value", [None, "", "   "])
def test_resolve_empty_returns_default(empty_value: str | None) -> None:
    descriptor = font_catalog.resolve(empty_value)
    assert descriptor.family == font_catalog.DEFAULT_FONT_FAMILY


def test_resolve_unknown_family_raises_value_error() -> None:
    with pytest.raises(ValueError, match="NotAFont"):
        font_catalog.resolve("NotAFont")


def test_resolve_is_case_sensitive() -> None:
    """The persisted family is canonical-case; resolve does not normalise."""
    with pytest.raises(ValueError):
        font_catalog.resolve("inter")


def test_available_returns_true_when_files_exist(tmp_path: Path) -> None:
    """``FontDescriptor.available`` checks both TTFs on disk."""
    workspace = tmp_path
    (workspace / "assets" / "fonts" / "Inter" / "static").mkdir(parents=True)
    descriptor = font_catalog.resolve("Inter")
    (workspace / descriptor.regular_path).write_bytes(b"\x00\x01")
    (workspace / descriptor.bold_path).write_bytes(b"\x00\x01")
    assert descriptor.available(workspace_dir=workspace) is True


def test_available_returns_false_when_files_missing(tmp_path: Path) -> None:
    descriptor = font_catalog.resolve("Inter")
    assert descriptor.available(workspace_dir=tmp_path) is False


def test_resolve_weighted_bold_returns_bold_path() -> None:
    """Feature 31: ``weight >= 700`` selects the bold cut for the family."""
    primary, bold = font_catalog.resolve_weighted("Manrope", "700")
    assert primary == Path("assets/fonts/Manrope/Bold.ttf")
    assert bold == Path("assets/fonts/Manrope/Bold.ttf")


def test_resolve_weighted_regular_returns_regular_path() -> None:
    """Weights below 700 fall back to the regular cut."""
    primary, bold = font_catalog.resolve_weighted("Manrope", "500")
    assert primary == Path("assets/fonts/Manrope/Regular.ttf")
    assert bold == Path("assets/fonts/Manrope/Bold.ttf")


def test_resolve_weighted_none_family_defaults_to_inter_regular() -> None:
    primary, bold = font_catalog.resolve_weighted(None, None)
    assert primary == Path("assets/fonts/Inter/static/Inter_28pt-Regular.ttf")
    assert bold == Path("assets/fonts/Inter/static/Inter_28pt-Bold.ttf")


def test_resolve_weighted_unknown_family_raises() -> None:
    """Unknown families propagate ``ValueError``; the ingest layer falls back."""
    with pytest.raises(ValueError):
        font_catalog.resolve_weighted("NotAFont", "700")


def test_resolve_weighted_invalid_weight_string_falls_back_to_regular() -> None:
    """Non-integer weight strings are treated as ``500`` (regular)."""
    primary, _bold = font_catalog.resolve_weighted("Manrope", "bold")
    assert primary == Path("assets/fonts/Manrope/Regular.ttf")


def test_available_against_repository_workspace_is_true_for_all_catalog() -> None:
    """Every catalogue entry must ship its TTFs under ``assets/fonts/``."""
    repo_root = Path(__file__).resolve().parents[3]
    for descriptor in font_catalog.AVAILABLE_FONTS:
        assert descriptor.available(workspace_dir=repo_root), (
            f"{descriptor.family} missing TTFs at "
            f"{descriptor.regular_path} or {descriptor.bold_path}"
        )
