# Exploration: Feature 16 — Layout Variant `side_banner` Implementation

**Date:** 2026-05-13  
**Scope:** Read-only analysis of rendering system to design `side_banner` layout variant  
**Status:** Complete spike — no code modifications

---

## 1. Current Layout System Architecture

### 1.1 Call Flow: From Reel to FFmpeg Filter

```
ReelPipeline / render_scripted_video
  ↓
PropertyRenderData + ResolvedRenderTemplateSettings (layout_variant="classic")
  ↓
build_overlay_layout(property_data, settings, slides, ...)
  ├─ Phase A: compose_top_panel() → BoxLayout + TextBlockLayout
  ├─ Phase B: compose_bottom_panel() → BoxLayout + TextBlockLayout + boxes
  └─ Phase C: compose_subtitle_segments() → TimedTextSegmentLayout
  ↓
OverlayLayout (frame_width, frame_height, panels, text_blocks, segments)
  ↓
build_overlay_filter() or build_filter_complex()
  ├─ drawbox for panels (color=black@0.46, @0.38)
  ├─ drawtext for text blocks (fontcolor=white or 0xF4D03F)
  └─ overlay for images (agent, logo, ber badge)
  ↓
ffmpeg filter_complex → rendered MP4 / poster JPG
```

### 1.2 Key Locations

| Module | File | Purpose |
|--------|------|---------|
| **Layout composition** | `modules/rendering/infrastructure/layout/composition.py:26–104` | Main orchestrator; computes `outer_margin_x/y`, delegates to 3 phases |
| **Panel geometry** | `modules/rendering/infrastructure/layout/panels.py:70–412` | `compose_top_panel()` (lines 70–203), `compose_bottom_panel()` (206–409) |
| **Subtitle timing** | `modules/rendering/infrastructure/layout/subtitles.py` | `compose_subtitle_segments()` — timed overlays |
| **Layout DTOs** | `modules/rendering/infrastructure/layout/models.py` | `BoxLayout`, `OverlayLayout`, `TextBlockLayout`, etc. |
| **Text measurement** | `modules/rendering/infrastructure/layout/text_measurement.py` | `measure_text_block()`, font size fitting logic |
| **FFmpeg filters** | `modules/rendering/infrastructure/ffmpeg/filters.py:36–172` | `build_overlay_filter()` — generates `drawbox`/`drawtext` commands |
| **Poster rendering** | `modules/rendering/infrastructure/poster.py:49–350` | Reuses `build_overlay_layout()` for static JPG |
| **Settings validation** | `modules/rendering/infrastructure/render_template_settings.py:22, 125–137` | `SUPPORTED_LAYOUT_VARIANTS` validation, `layout_variant` field |
| **Agency settings** | `modules/configuration/domain/agency_settings.py:87–102` | `RenderTemplate` domain — `layout_variant: str` exists |

### 1.3 Current "Classic" Layout Geometry

**File:** `composition.py:39–43`

```python
outer_margin_x = max(36, round(width * 0.04))  # ~4% of width, min 36px
outer_margin_y = max(36, round(height * 0.03))  # ~3% of height, min 36px
panel_padding_x = max(26, round(width * 0.024))
panel_padding_y = max(22, round(height * 0.018))
panel_width = width - (outer_margin_x * 2)  # Full width - margins
```

**Top panel:** 
- Position: `(outer_margin_x, outer_margin_y)` — top-left with margins
- Width: `panel_width` (full - margins)
- Height: Dynamic based on content (160–340px range)

**Bottom panel:**
- Position: `(outer_margin_x, computed_y)` — bottom placement
- Width: `panel_width` (full - margins)
- Height: Dynamic based on content (208–500px range)

### 1.4 FFmpeg Filter Graph Structure (Classic)

**File:** `filters.py:70–85`

```python
# Top panel background
drawbox=x=...:y=...:w=...:h=...:color=black@0.38:t=fill

# Bottom panel background
drawbox=x=...:y=...:w=...:h=...:color=black@0.46:t=fill

# Text blocks for both panels
for block in overlay.text_blocks:
    drawtext=fontfile=...:text=...:fontcolor={resolve_text_color(block.block)}:...
```

**Color resolution:** `formatting.py:80–81`
- `resolve_text_color(block_name)` returns hardcoded `OVERLAY_TEXT_COLORS` dict (all white except subtitles yellow)
- No per-property color override currently supported

### 1.5 Poster Generation (Static JPG)

**File:** `poster.py:263–350`

```python
overlay_layout = build_overlay_layout(...)  # Reuses same layout logic
# Then wraps result in ffmpeg to blur background + overlay images
```

The poster reuses the **exact same layout geometry** as the video reel. Changes to layout geometry automatically propagate to posters.

---

## 2. Proposed Changes for `side_banner` Layout

### 2.1 Layout Variant Registration

**File:** `render_template_settings.py:22`

```python
SUPPORTED_LAYOUT_VARIANTS = frozenset({"classic", "side_banner"})
```

**Validation:** Already in place at lines 125–137.

---

### 2.2 Passing `layout_variant` to `build_overlay_layout()`

**Current signature** (`composition.py:26–36`):
```python
def build_overlay_layout(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    slide_duration: float | None,
    has_ber_badge: bool,
    has_agency_logo: bool = False,
    cover_caption: str | None = None,
    single_line_contact_email: bool = False,
) -> OverlayLayout:
```

**Problem:** `PropertyReelTemplate` does NOT contain `layout_variant` — that field lives in `ResolvedRenderTemplateSettings` (only used at the orchestration layer).

**Proposed solution — Option A (Recommended):**
Add `layout_variant: str = "classic"` as optional keyword-only parameter to `build_overlay_layout()`:

```python
def build_overlay_layout(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    slide_duration: float | None,
    has_ber_badge: bool,
    has_agency_logo: bool = False,
    cover_caption: str | None = None,
    single_line_contact_email: bool = False,
    layout_variant: str = "classic",  # NEW
) -> OverlayLayout:
```

**Rationale:**
- Non-breaking change (defaults to "classic")
- Minimal signature bloat
- Call sites that don't care don't need modification

**Call sites to update:**
1. `composition.py:26` — signature
2. `ffmpeg/filters.py:51` — explicit layout parameter already (line 51 uses `layout=...`)
3. `ffmpeg/render_reel.py:???` — TBD (search for `build_overlay_layout`)
4. `preparation.py:???` — TBD
5. `poster.py:273` — explicit call with overrides
6. `tests/unit/rendering/test_layout_composition.py` — test calls

All **caller sites are localized:** composition is only invoked from filters, poster, and tests. **Medium change complexity.**

---

### 2.3 Geometry for `side_banner` Variant

#### New Top Panel Layout
- **Position:** top-left, same `(outer_margin_x, outer_margin_y)`
- **Width:** ~60–70% of usable width (e.g., `round(panel_width * 0.65)`)
- **Height:** Dynamic, same as classic
- **Right edge** leaves room for vertical banner

#### New Bottom Panel Layout
- **Position:** full-width bottom (same as classic)
- **Width:** `panel_width` (full - margins)
- **Height:** Dynamic, same as classic
- **Composition:** photo + agent name/info on left; agency logo card on right

#### Vertical "FOR SALE" Banner
- **Position:** right edge, anchored at `x = settings.width - banner_width - outer_margin_x`
- **Height:** Spans from top panel area to near bottom panel
- **Width:** ~40–60px
- **Rotation:** 90 degrees (text reads top-to-bottom)
- **Text:** Via `build_status_ribbon_text(property_data)` (already exists in `formatting.py`)
- **Color:** Per-property via `wppd_accent_background_color` HEX with alpha
- **Text color:** Per-property via `wppd_accent_text_color` HEX (fallback: white)

#### Full-Bleed Photo
- **Key difference:** No `outer_margin_x` / `outer_margin_y` around photo
- **Approach:** When `layout_variant == "side_banner"`, use `outer_margin_x = 0`, `outer_margin_y = 0` for geometry
- **Photo bounds:** 0..width, 0..height (except space reserved for banner on right)

---

### 2.4 Rotated Banner Implementation (FFmpeg Workaround)

**Problem:** `drawtext` filter does **NOT** support native rotation.

**Realistic options:**

#### Option A: Pre-render Text to PNG, Overlay as Image (RECOMMENDED)
- **When:** During preparation phase, before filter graph generation
- **How:** Use PIL (already imported in `preparation.py`) to render text as PNG
- **Then:** Overlay as image input to ffmpeg (like agent photo, logo)
- **Advantages:**
  - Clean separation: text rendering ≠ ffmpeg
  - Easy to apply rotation via PIL's `Image.rotate()`
  - Can apply effects (shadow, border) in PIL
  - Reusable for other rotated elements
- **Disadvantages:**
  - Extra file I/O in preparation phase
  - One more ffmpeg input stream

#### Option B: Rotate Entire Input Stream via `rotate` Filter
- **How:** Create a dedicated input video (e.g., blank 60px wide) with drawtext, apply `rotate=PI/2`, then overlay
- **Advantages:**
  - No pre-rendering needed
  - All in ffmpeg filter graph
- **Disadvantages:**
  - Complex filter graph (new input, concat, rotation)
  - Harder to control exact positioning after rotation
  - Scaling artifacts possible

#### Option C: Use `transpose` Filter
- `transpose=1` rotates 90° CW
- Same limitations as Option B

**Recommendation: Option A (PIL pre-render)**
- Mirrors existing pattern: agent image, logo are pre-prepared PNGs
- Add new "banner image" to `PreparedReelAssets`
- In `preparation.py`, add `_render_status_banner_image()` function
- Overlay in filter graph like any other image

---

### 2.5 Parametrizable Panel Colors

**Current hardcoding** (`filters.py:73–85`):
```python
drawbox=...color=black@0.46:...  # bottom
drawbox=...color=black@0.38:...  # top
```

**Per-property accent colors:**
- `wppd_accent_background_color` (HEX, e.g., "#FF5733") with alpha override
- `wppd_accent_text_color` (HEX, e.g., "#FFFFFF")
- Fallback: `BrandSettings.primary_color` from agency

**Solution: Add Optional Parameters to `build_overlay_filter()`**

**Current signature** (`filters.py:36–50`):
```python
def build_overlay_filter(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    cover_caption: str | None = None,
    slide_captions: Sequence[str | None] = (),
    slide_duration: float | None = None,
    video_input_label: str = "video_base",
    agent_image_label: str = "agent_panel_image",
    logo_image_label: str | None = None,
    has_agency_logo: bool | None = None,
    ber_icon_label: str | None = None,
    output_label: str = "vout",
    layout: OverlayLayout | None = None,
) -> str:
```

**Add optional color parameters:**
```python
def build_overlay_filter(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    cover_caption: str | None = None,
    slide_captions: Sequence[str | None] = (),
    slide_duration: float | None = None,
    video_input_label: str = "video_base",
    agent_image_label: str = "agent_panel_image",
    logo_image_label: str | None = None,
    has_agency_logo: bool | None = None,
    ber_icon_label: str | None = None,
    output_label: str = "vout",
    layout: OverlayLayout | None = None,
    top_panel_color: str | None = None,      # NEW: hex@alpha or "black@0.38"
    bottom_panel_color: str | None = None,   # NEW: hex@alpha or "black@0.46"
) -> str:
```

**Implementation location:** `filters.py:70–85`
```python
top_color = top_panel_color or "black@0.38"
bottom_color = bottom_panel_color or "black@0.46"

if active_layout.bottom_panel is not None and active_layout.bottom_panel.visible:
    text_filters.append(
        f"drawbox=...color={bottom_color}:t=fill"
    )
if active_layout.top_panel is not None and active_layout.top_panel.visible:
    text_filters.append(
        f"drawbox=...color={top_color}:t=fill"
    )
```

**Text color resolution** (`formatting.py:80–81`):

Current:
```python
def resolve_text_color(block: str) -> str:
    return OVERLAY_TEXT_COLORS.get(block, OVERLAY_TEXT_COLOR_PRIMARY)
```

**Needs enhancement** to accept optional override:
```python
def resolve_text_color(block: str, override_color: str | None = None) -> str:
    if override_color is not None:
        return override_color
    return OVERLAY_TEXT_COLORS.get(block, OVERLAY_TEXT_COLOR_PRIMARY)
```

**Call sites to update:**
- `filters.py:96` — top panel text color
- `filters.py:111` — subtitle color (may need separate param)

---

### 2.6 Photo Full-Bleed Strategy

**Current:** `outer_margin_x` and `outer_margin_y` create borders around the photo.

**For `side_banner`:** Photo should be full-bleed (no margins), but panels/banner need positioning.

**Proposed solution:**

**Option A (Simplest): Conditional Zero Margins in `composition.py`**

```python
def build_overlay_layout(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    ...
    layout_variant: str = "classic",
) -> OverlayLayout:
    width = settings.width
    height = settings.height
    
    # Conditionally zero margins for side_banner
    if layout_variant == "side_banner":
        outer_margin_x = 0
        outer_margin_y = 0
    else:
        outer_margin_x = max(36, round(width * 0.04))
        outer_margin_y = max(36, round(height * 0.03))
    
    panel_padding_x = max(26, round(width * 0.024))
    panel_padding_y = max(22, round(height * 0.018))
    panel_width = width - (outer_margin_x * 2)
```

**Rationale:**
- Minimal change: 3 new lines in `build_overlay_layout()`
- Panels automatically "float" over full-bleed photo
- Banner anchoring to `width - banner_width` naturally works
- No new data structures needed

**Option B: Dedicated Module**
- `modules/rendering/infrastructure/layout/side_banner.py` — parallel to `panels.py`
- Separate `compose_top_panel_side_banner()`, `compose_bottom_panel_side_banner()`
- Overkill for now; defer to Phase 4

**Recommendation: Option A** (simpler, matches current architecture)

---

### 2.7 Configuration Domain

**File:** `modules/configuration/domain/agency_settings.py:87–102`

Already in place:
```python
@dataclass(frozen=True, slots=True)
class RenderTemplate:
    template_id: str
    ...
    layout_variant: str  # Line 94 — ALREADY EXISTS!
    reel_settings: Mapping[str, Any] = field(default_factory=dict)
    ...
```

**Action:** Just add `"side_banner"` to `SUPPORTED_LAYOUT_VARIANTS` frozenset.

---

### 2.8 Database Migration & Template Seeding

**File:** `alembic/versions/20260513_0002_render_templates.py:46–66`

Current migration seeds only the "classic" template:
```python
op.execute("""
    INSERT INTO render_templates (
        template_id, display_name, description, status, sort_order,
        preview_images, layout_variant, reel_settings, poster_settings,
        created_at, updated_at
    ) VALUES (
        'classic',
        'Classic',
        'The original 4Reels renderer layout and settings.',
        'active',
        0,
        '[]'::jsonb,
        'classic',  # layout_variant = 'classic'
        '{}'::jsonb,
        '{}'::jsonb,
        timezone('utc', now()),
        timezone('utc', now())
    ) ON CONFLICT (template_id) DO NOTHING
""")
```

**To add side_banner via migration:**

Create new migration `20260513_0003_render_template_side_banner.py`:
```python
op.execute("""
    INSERT INTO render_templates (
        template_id, display_name, description, status, sort_order,
        preview_images, layout_variant, reel_settings, poster_settings,
        created_at, updated_at
    ) VALUES (
        'side_banner',
        'Side Banner',
        'Layout with full-bleed photo, top panel, and vertical "FOR SALE" banner on the right.',
        'active',
        1,
        '[]'::jsonb,
        'side_banner',  # NEW
        '{}'::jsonb,
        '{}'::jsonb,
        timezone('utc', now()),
        timezone('utc', now())
    ) ON CONFLICT (template_id) DO NOTHING
""")
```

**Alternative:** Hit `/v1/admin/render-templates` endpoint if it exists (check `modules/configuration/transport/`).

---

## 3. Implementation Checklist

### Phase 3A: Core Geometry & Configuration
- [ ] Add `"side_banner"` to `SUPPORTED_LAYOUT_VARIANTS` (`render_template_settings.py:22`)
- [ ] Add `layout_variant: str = "classic"` parameter to `build_overlay_layout()` (`composition.py:26`)
- [ ] Add conditional `outer_margin_x/y = 0` logic in `composition.py:39–43`
- [ ] Pass `layout_variant` through all call sites (filters, poster, render_reel, preparation)
- [ ] Create migration `20260513_0003_*.py` to seed `side_banner` template

### Phase 3B: Panel Colors (Optional, if Needed)
- [ ] Add `top_panel_color`, `bottom_panel_color` params to `build_overlay_filter()` (`filters.py:36`)
- [ ] Enhance `resolve_text_color()` to accept override (`formatting.py:80`)
- [ ] Update panel drawing logic (`filters.py:70–85`)
- [ ] Add color resolution from `property_data` (TBD: field not yet added to `PropertyRenderData`)

### Phase 3C: Rotated Banner (If Adopting Option A)
- [ ] Add `banner_image_path` to `PreparedReelAssets` (`models.py:94–103`)
- [ ] Implement `_render_status_banner_image()` in `preparation.py`
- [ ] Update filter graph to overlay banner image (like agent photo)

### Phase 3D: Tests
- [ ] Extend `test_layout_composition.py` with `side_banner` test case
- [ ] Extend `test_render_template_settings.py` to verify `side_banner` in `SUPPORTED_LAYOUT_VARIANTS`
- [ ] Add integration test in `test_render_templates_router.py` for template creation

---

## 4. Risks & Regressions

### High-Risk Areas
1. **Outer margin zero-ing:** Panels positioned at `(0, 0)` must be visually tested to ensure no clipping
2. **Banner rotation:** FFmpeg doesn't natively rotate text; PIL pre-render adds I/O overhead
3. **Panel color parametrization:** If property data doesn't have color fields, fallback logic must be robust
4. **Poster generation:** Changes to geometry auto-propagate to posters; must test both video + poster

### Testing Strategy
- **Unit tests:** Layout geometry (margins, panel positions) for both `classic` and `side_banner`
- **Integration tests:** Render a full reel with `side_banner` template, inspect MP4 + poster JPG
- **Visual regression:** Compare "classic" renders before/after changes (should be byte-for-byte identical)

---

## 5. Implementation Order (Recommended)

1. **Foundations (Day 1):**
   - Register `"side_banner"` in frozenset
   - Add `layout_variant` parameter to `build_overlay_layout()`
   - Update all call sites (mechanical change)
   - Create migration
   - Run tests (should still pass for `classic`)

2. **Zero-margin geometry (Day 2):**
   - Add conditional `outer_margin_x = 0` in `composition.py`
   - Test with `layout_variant == "side_banner"`
   - Verify panels float over full-bleed background

3. **Panel colors (Day 3, if needed):**
   - Add color parameters to `build_overlay_filter()`
   - Extend `PropertyRenderData` with `wppd_accent_*` fields
   - Update property data loading to populate these

4. **Banner rotation (Day 4, if adopting PIL approach):**
   - Implement `_render_status_banner_image()` in `preparation.py`
   - Add to `PreparedReelAssets`
   - Update filter graph to overlay

5. **Integration & testing (Day 5):**
   - End-to-end reel + poster render with `side_banner`
   - Visual inspection
   - Regression test suite

---

## 6. File Changes Summary

| File | Change | Complexity |
|------|--------|-----------|
| `render_template_settings.py:22` | Add frozenset entry | Trivial |
| `layout/composition.py:26–43` | Add param + conditional margins | Low |
| `ffmpeg/filters.py:36–50` | Add color params | Low |
| `formatting.py:80` | Enhance `resolve_text_color()` | Low |
| `ffmpeg/render_reel.py` | Pass `layout_variant` | Low (mechanical) |
| `preparation.py` | Pass `layout_variant`; optionally add banner rendering | Medium |
| `poster.py:273` | Pass `layout_variant` | Low |
| `models.py` | Optionally add `banner_image_path` | Low |
| `alembic/versions/20260513_0003_*.py` | New migration | Low |
| `tests/unit/rendering/test_layout_composition.py` | Add `side_banner` test | Low |
| `tests/unit/rendering/test_render_template_settings.py` | Verify frozenset | Trivial |
| `tests/integration/configuration/test_render_templates_router.py` | Add template creation test | Low |

**Total complexity:** Low–Medium. No architectural changes; pure feature addition.

---

## 7. Open Questions

1. **Per-property accent colors:** Does `PropertyRenderData` already have `wppd_accent_background_color` and `wppd_accent_text_color` fields? (Not found in current `models.py:107–138`.)
   - If not: where should they be added? Property catalog schema or render data envelope?
   - If yes: where are they populated?

2. **Banner text:** Is `build_status_ribbon_text(property_data)` the correct source? (Assume yes — used for classic top panel.)

3. **Banner sizing:** Hardcode width (e.g., 50px) or compute from frame dimensions?

4. **Intro mode:** Should the banner appear in intro slides? Check `settings.include_intro` behavior.

5. **Subtitle positioning:** With zero margins, where do subtitles appear? (Likely centered on full-width photo.)

---

## 8. Architecture Diagram

```
ResolvedRenderTemplateSettings
  ├─ layout_variant="side_banner"
  └─ reel_template: PropertyReelTemplate
      ├─ width, height, fps, ...
      └─ (no layout_variant field)

                    ↓

build_overlay_layout(..., layout_variant="side_banner")
  │
  ├─ if layout_variant == "side_banner":
  │   outer_margin_x = 0
  │   outer_margin_y = 0
  │ else:
  │   outer_margin_x = max(36, ...)
  │   outer_margin_y = max(36, ...)
  │
  ├─ panel_width = width - (outer_margin_x * 2)
  │
  ├─ compose_top_panel(..., outer_margin_x=0, panel_width=...)
  │   → reduced panel width (60% for side_banner)
  │
  ├─ compose_bottom_panel(..., outer_margin_x=0, panel_width=...)
  │   → full-width panels
  │
  └─ compose_subtitle_segments(...)
      → subtitles on full-width background

                    ↓

OverlayLayout(top_panel, bottom_panel, text_blocks, ...)

                    ↓

build_overlay_filter(..., layout_variant="side_banner")
  │
  ├─ drawbox(top_panel, color=override or "black@0.38")
  ├─ drawbox(bottom_panel, color=override or "black@0.46")
  ├─ drawtext(text_blocks)
  │
  └─ overlay(banner_image)  ← PIL-rendered + rotated

                    ↓

ffmpeg → MP4 reel / poster JPG
```

---

End of exploration. Ready for implementation.
