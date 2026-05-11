"""Unit tests for `modules.rendering.infrastructure.layout.text_measurement`."""

from __future__ import annotations

from modules.rendering.infrastructure.layout.text_measurement import (
    MeasuredTextBlock,
    _candidate_font_sizes,
    _wrap_width_from_pixels,
    measure_address_blocks,
    measure_text_block,
)


def test_measure_text_block_returns_none_for_empty_text() -> None:
    assert (
        measure_text_block(
            block="address",
            text=None,
            usable_width=400,
            max_lines=2,
            max_font_size=32,
            min_font_size=18,
            min_chars=10,
        )
        is None
    )
    assert (
        measure_text_block(
            block="address",
            text="   ",
            usable_width=400,
            max_lines=2,
            max_font_size=32,
            min_font_size=18,
            min_chars=10,
        )
        is None
    )


def test_measure_text_block_picks_largest_font_size_that_fits() -> None:
    measured = measure_text_block(
        block="price",
        text="500000",
        usable_width=600,
        max_lines=1,
        max_font_size=48,
        min_font_size=24,
        min_chars=4,
    )
    assert measured is not None
    assert measured.block == "price"
    assert measured.font_size == 48
    assert measured.clamped is False
    assert measured.warning is None
    assert measured.lines == ("500000",)


def test_measure_text_block_clamps_long_text_with_warning() -> None:
    long_text = " ".join(["word"] * 200)
    measured = measure_text_block(
        block="address",
        text=long_text,
        usable_width=120,
        max_lines=1,
        max_font_size=32,
        min_font_size=24,
        min_chars=6,
    )
    assert measured is not None
    assert measured.clamped is True
    assert measured.warning is not None
    assert measured.warning.block == "address"
    assert measured.warning.code == "TEXT_CLAMPED"


def test_candidate_font_sizes_decreasing_step_includes_min_size() -> None:
    sizes = _candidate_font_sizes(40, 24, step=4)
    assert sizes[0] == 40
    assert sizes[-1] == 24
    assert all(a >= b for a, b in zip(sizes, sizes[1:]))


def test_candidate_font_sizes_appends_min_when_step_skips_it() -> None:
    sizes = _candidate_font_sizes(20, 13, step=4)
    assert 13 in sizes
    assert sizes[0] == 20


def test_wrap_width_from_pixels_floor_at_min_chars() -> None:
    width = _wrap_width_from_pixels(
        usable_width=80,
        font_size=32,
        min_chars=10,
    )
    assert width >= 10


def test_wrap_width_from_pixels_scales_with_usable_width() -> None:
    narrow = _wrap_width_from_pixels(usable_width=300, font_size=24, min_chars=4)
    wide = _wrap_width_from_pixels(usable_width=900, font_size=24, min_chars=4)
    assert wide > narrow


def test_measure_address_blocks_returns_empty_when_all_inputs_blank() -> None:
    result = measure_address_blocks(
        address=None,
        viewing_times=None,
        details=None,
        usable_width=400,
        max_lines=4,
        max_font_size=32,
        min_font_size=22,
        min_chars=18,
    )
    assert result == ()


def test_measure_address_blocks_combines_address_viewing_times_details() -> None:
    blocks = measure_address_blocks(
        address="110 Example Road, Dublin 14",
        viewing_times="Viewing by appointment",
        details="3 bed | 2 bath | A1",
        usable_width=400,
        max_lines=4,
        max_font_size=32,
        min_font_size=22,
        min_chars=18,
    )
    block_names = [b.block for b in blocks]
    assert "address" in block_names
    assert "viewing_times" in block_names
    assert "address_meta" in block_names
    for block in blocks:
        assert isinstance(block, MeasuredTextBlock)
        assert block.lines


def test_measure_address_blocks_emits_warning_when_address_clamped() -> None:
    blocks = measure_address_blocks(
        address=" ".join(["very-long-address-token"] * 80),
        viewing_times=None,
        details=None,
        usable_width=120,
        max_lines=1,
        max_font_size=24,
        min_font_size=22,
        min_chars=18,
    )
    assert blocks
    address_block = next(b for b in blocks if b.block == "address")
    assert address_block.clamped is True
    assert address_block.warning is not None
    assert address_block.warning.block == "address"
