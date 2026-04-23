from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from services.media.reel_rendering.manifest import build_property_reel_manifest_from_data
from services.media.reel_rendering.layout import build_overlay_layout
from services.media.reel_rendering.models import (
    PreparedReelAssets,
    PreparedReelSlide,
    PropertyReelSlide,
    PropertyRenderData,
    PropertyReelTemplate,
)
from services.media.reel_rendering.formatting import format_property_size, format_property_size_header
from services.media.reel_rendering.poster import (
    _build_poster_filter_script,
    _resolve_poster_photo_box,
    generate_property_poster_from_data,
)
from services.media.reel_rendering.preparation import prepare_reel_render_assets
from services.media.reel_rendering.render import (
    _build_concat_command,
    _build_slide_segment_filter,
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
)
from services.media.reel_rendering.runtime import (
    compute_segment_timing,
    resolve_background_audio_paths,
    resolve_ffmpeg_binary,
)
from settings.app import AppSettings


@contextmanager
def _workspace_temp_dir() -> Iterator[Path]:
    temp_root = APPLICATION_ROOT / ".tmp_test_cases"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_root / f"case_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class _FFmpegTestCase(unittest.TestCase):
    @staticmethod
    def _ffmpeg_binary() -> str:
        return resolve_ffmpeg_binary()

    def _run_ffmpeg(self, command: list[str]) -> None:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr.strip())

    def _create_image(self, output_path: Path, size: str, color: str) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_ffmpeg(
            [
                self._ffmpeg_binary(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={size}:d=1",
                "-frames:v",
                "1",
                str(output_path),
            ]
        )

    def _create_vertical_stripe_image(self, output_path: Path, size: str) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_ffmpeg(
            [
                self._ffmpeg_binary(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={size}:d=1",
                "-vf",
                (
                    "drawbox=x=0:y=0:w=iw/3:h=ih:color=0xFF0000:t=fill,"
                    "drawbox=x=iw/3:y=0:w=iw/3:h=ih:color=0x00FF00:t=fill,"
                    "drawbox=x=2*iw/3:y=0:w=iw/3:h=ih:color=0x0000FF:t=fill"
                ),
                "-frames:v",
                "1",
                str(output_path),
            ]
        )

    def _create_audio_asset(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_ffmpeg(
            [
                self._ffmpeg_binary(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:duration=2",
                "-c:a",
                "mp3",
                str(output_path),
            ]
        )

    def _probe_image_dimensions(self, path: Path) -> tuple[int, int]:
        completed = subprocess.run(
            [self._ffmpeg_binary(), "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        match = re.search(r"Video:.*?,.*?,\s*(\d+)x(\d+)\b", completed.stderr)
        self.assertIsNotNone(match, completed.stderr)
        assert match is not None
        return int(match.group(1)), int(match.group(2))

    def _probe_video_stream(self, path: Path) -> tuple[int, int, float]:
        completed = subprocess.run(
            [self._ffmpeg_binary(), "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        match = re.search(
            r"Video:.*?,.*?,\s*(\d+)x(\d+)\b.*?(\d+(?:\.\d+)?) fps",
            completed.stderr,
        )
        self.assertIsNotNone(match, completed.stderr)
        assert match is not None
        return int(match.group(1)), int(match.group(2)), float(match.group(3))

    def _sample_pixel_rgb(self, path: Path, x: int, y: int) -> tuple[int, int, int]:
        sample_x = max(0, x - (x % 2))
        sample_y = max(0, y - (y % 2))
        completed = subprocess.run(
            [
                self._ffmpeg_binary(),
                "-v",
                "error",
                "-i",
                str(path),
                "-vf",
                f"crop=2:2:{sample_x}:{sample_y},scale=1:1:flags=neighbor,format=rgb24",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr.decode("utf-8", errors="replace").strip())
        self.assertGreaterEqual(len(completed.stdout), 3)
        return tuple(completed.stdout[:3])

    @staticmethod
    def _build_property_data(
        *,
        selected_dir: Path,
        selected_paths: tuple[Path, ...],
        price: str | None = "500000",
        property_status: str | None = "For Sale",
        banner_text: str | None = None,
        price_display_text: str | None = None,
    ) -> PropertyRenderData:
        return PropertyRenderData(
            site_id="ckp.ie",
            property_id=173637,
            slug="sample-property",
            title="110 Example Road, Dublin 14",
            link="https://ckp.ie/property/sample-property",
            property_status=property_status,
            selected_image_dir=selected_dir,
            selected_image_paths=selected_paths,
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating=None,
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price=price,
            property_type_label="Apartment",
            property_area_label="Dublin 14",
            property_county_label="Dublin",
            eircode="D14 TEST",
            banner_text=banner_text,
            price_display_text=price_display_text,
        )


class ReelConfigurationTests(unittest.TestCase):
    def test_property_media_cleanup_flags_default_to_current_behavior(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = AppSettings(_env_file=None)

        self.assertTrue(settings.property_media_delete_temporary_files)
        self.assertFalse(settings.property_media_delete_selected_photos)

    def test_property_media_cleanup_flags_accept_boolean_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROPERTY_MEDIA_DELETE_TEMPORARY_FILES": "false",
                "PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS": "true",
            },
            clear=True,
        ):
            settings = AppSettings(_env_file=None)

        self.assertFalse(settings.property_media_delete_temporary_files)
        self.assertTrue(settings.property_media_delete_selected_photos)

    def test_reel_and_poster_output_settings_default_to_current_targets(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = AppSettings(_env_file=None)

        self.assertEqual(settings.reel_width, 1080)
        self.assertEqual(settings.reel_height, 1440)
        self.assertEqual(settings.reel_fps, 24)
        self.assertEqual(settings.poster_width, 1080)
        self.assertEqual(settings.poster_height, 1920)
        self.assertEqual(settings.poster_footer_bottom_offset_px, 56)

    def test_reel_and_poster_output_settings_allow_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "REEL_WIDTH": "720",
                "REEL_HEIGHT": "960",
                "REEL_FPS": "30",
                "POSTER_WIDTH": "720",
                "POSTER_HEIGHT": "1280",
                "POSTER_FOOTER_BOTTOM_OFFSET_PX": "104",
            },
            clear=True,
        ):
            settings = AppSettings(_env_file=None)

        self.assertEqual(settings.reel_width, 720)
        self.assertEqual(settings.reel_height, 960)
        self.assertEqual(settings.reel_fps, 30)
        self.assertEqual(settings.poster_width, 720)
        self.assertEqual(settings.poster_height, 1280)
        self.assertEqual(settings.poster_footer_bottom_offset_px, 104)

    def test_persistent_logging_settings_default_to_workspace_logs(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = AppSettings(_env_file=None)

        self.assertTrue(settings.persistent_logging_enabled)
        self.assertEqual(settings.persistent_log_directory, "logs")
        self.assertEqual(settings.persistent_log_backup_count, 20)
        self.assertEqual(settings.persistent_log_max_bytes, 25_000_000)

    def test_persistent_logging_settings_allow_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PERSISTENT_LOGGING_ENABLED": "false",
                "PERSISTENT_LOG_DIRECTORY": "runtime-logs",
                "PERSISTENT_LOG_MAX_BYTES": "5000000",
                "PERSISTENT_LOG_BACKUP_COUNT": "7",
            },
            clear=True,
        ):
            settings = AppSettings(_env_file=None)

        self.assertFalse(settings.persistent_logging_enabled)
        self.assertEqual(settings.persistent_log_directory, "runtime-logs")
        self.assertEqual(settings.persistent_log_max_bytes, 5_000_000)
        self.assertEqual(settings.persistent_log_backup_count, 7)

    def test_full_seven_slide_reel_distributes_frames_to_match_configured_total(self) -> None:
        template = PropertyReelTemplate(
            fps=24,
            max_slide_count=7,
            include_intro=False,
            intro_duration_seconds=0.0,
            total_duration_seconds=38.0,
            seconds_per_slide=4.0,
        )

        segment_frames, segment_durations, total_duration = compute_segment_timing(template, 7)

        self.assertEqual(sum(segment_frames), 912)
        self.assertEqual(segment_frames.count(131), 2)
        self.assertEqual(segment_frames.count(130), 5)
        self.assertEqual(sum(segment_durations), 38.0)
        self.assertEqual(total_duration, 38.0)


class OverlayLayoutTests(unittest.TestCase):
    def test_format_property_size_keeps_only_square_meters_when_square_feet_are_present(self) -> None:
        self.assertEqual(format_property_size("188 sq.m. (2,024 sq.ft.)"), "188 m²")
        self.assertEqual(format_property_size_header("188 sq.m. (2,024 sq.ft.)"), "188m²")

    def test_bottom_panel_grows_and_keeps_agent_logo_and_text_within_bounds(self) -> None:
        property_data = _FFmpegTestCase._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(Path("selected_photos/primary_image.png"),),
        )
        slide = PropertyReelSlide(
            image_path=Path("selected_photos/primary_image.png"),
            caption="Bright family home.",
        )
        template = PropertyReelTemplate(
            width=320,
            height=480,
            subtitle_font_size=28,
        )

        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(slide,),
            slide_duration=template.seconds_per_slide,
            has_ber_badge=False,
            has_agency_logo=True,
            cover_caption=None,
        )

        self.assertIsNotNone(overlay_layout.bottom_panel)
        assert overlay_layout.bottom_panel is not None
        self.assertGreaterEqual(overlay_layout.bottom_panel.height, 208)

        if overlay_layout.agent_image_box is not None:
            self.assertGreaterEqual(overlay_layout.agent_image_box.x, overlay_layout.bottom_panel.x)
            self.assertGreaterEqual(overlay_layout.agent_image_box.y, overlay_layout.bottom_panel.y)
            self.assertLessEqual(
                overlay_layout.agent_image_box.x + overlay_layout.agent_image_box.width,
                overlay_layout.bottom_panel.x + overlay_layout.bottom_panel.width,
            )
            self.assertLessEqual(
                overlay_layout.agent_image_box.y + overlay_layout.agent_image_box.height,
                overlay_layout.bottom_panel.y + overlay_layout.bottom_panel.height,
            )

        self.assertIsNotNone(overlay_layout.agency_logo_box)
        assert overlay_layout.agency_logo_box is not None
        self.assertGreaterEqual(overlay_layout.agency_logo_box.x, overlay_layout.bottom_panel.x)
        self.assertGreaterEqual(overlay_layout.agency_logo_box.y, overlay_layout.bottom_panel.y)
        self.assertLessEqual(
            overlay_layout.agency_logo_box.x + overlay_layout.agency_logo_box.width,
            overlay_layout.bottom_panel.x + overlay_layout.bottom_panel.width,
        )
        self.assertLessEqual(
            overlay_layout.agency_logo_box.y + overlay_layout.agency_logo_box.height,
            overlay_layout.bottom_panel.y + overlay_layout.bottom_panel.height,
        )

        for block in overlay_layout.text_blocks:
            if not block.block.startswith("agent_"):
                continue
            self.assertGreaterEqual(block.x, overlay_layout.bottom_panel.x)
            self.assertGreaterEqual(block.y, overlay_layout.bottom_panel.y)
            self.assertLessEqual(
                block.x + block.max_width,
                overlay_layout.bottom_panel.x + overlay_layout.bottom_panel.width,
            )
            self.assertLessEqual(
                block.y + block.box_height,
                overlay_layout.bottom_panel.y + overlay_layout.bottom_panel.height,
            )

    def test_bottom_panel_moves_up_when_footer_offset_is_configured(self) -> None:
        property_data = _FFmpegTestCase._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(Path("selected_photos/primary_image.png"),),
        )
        slide = PropertyReelSlide(
            image_path=Path("selected_photos/primary_image.png"),
            caption="Bright family home.",
        )
        default_template = PropertyReelTemplate(
            width=360,
            height=640,
            subtitle_font_size=28,
        )
        shifted_template = PropertyReelTemplate(
            width=360,
            height=640,
            subtitle_font_size=28,
            footer_bottom_offset_px=48,
        )

        default_layout = build_overlay_layout(
            property_data,
            default_template,
            slides=(slide,),
            slide_duration=default_template.seconds_per_slide,
            has_ber_badge=False,
            has_agency_logo=True,
            cover_caption=None,
        )
        shifted_layout = build_overlay_layout(
            property_data,
            shifted_template,
            slides=(slide,),
            slide_duration=shifted_template.seconds_per_slide,
            has_ber_badge=False,
            has_agency_logo=True,
            cover_caption=None,
        )

        self.assertIsNotNone(default_layout.bottom_panel)
        self.assertIsNotNone(shifted_layout.bottom_panel)
        assert default_layout.bottom_panel is not None
        assert shifted_layout.bottom_panel is not None
        self.assertEqual(default_layout.bottom_panel.y - shifted_layout.bottom_panel.y, 48)


class ReelPreparationIntegrationTests(_FFmpegTestCase):
    def test_prepare_reel_render_assets_normalizes_mixed_photo_sizes(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            self._create_audio_asset(workspace_dir / "assets" / "music" / "test.mp3")
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            source_paths = [
                selected_dir / "primary_image.png",
                selected_dir / "01_landscape.png",
                selected_dir / "02_portrait.png",
                selected_dir / "03_small.png",
            ]
            self._create_image(source_paths[0], "2400x1400", "red")
            self._create_image(source_paths[1], "2200x1200", "blue")
            self._create_image(source_paths[2], "1200x2200", "green")
            self._create_image(source_paths[3], "160x120", "yellow")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=tuple(source_paths),
            )
            template = PropertyReelTemplate(
                width=320,
                height=480,
                fps=12,
                max_slide_count=4,
                include_intro=False,
                intro_duration_seconds=0.0,
                total_duration_seconds=2.0,
                seconds_per_slide=0.5,
                background_audio_filename="music/test.mp3",
            )

            prepared_assets = prepare_reel_render_assets(
                workspace_dir,
                property_data,
                template=template,
                working_dir=workspace_dir / "_prepared",
            )

            self.assertEqual(len(prepared_assets.slides), 4)
            slide_frames = round(template.seconds_per_slide * template.fps)
            for prepared_slide in prepared_assets.slides:
                self.assertEqual(
                    self._probe_image_dimensions(prepared_slide.working_path),
                    (prepared_slide.working_width, prepared_slide.working_height),
                )
                self.assertGreater(prepared_slide.working_width, template.width)
                self.assertGreater(prepared_slide.working_height, template.height)
                self.assertIn(
                    prepared_slide.motion_mode,
                    {"horizontal"},
                )
                self.assertGreaterEqual(prepared_slide.working_width - template.width, slide_frames)

    def test_prepare_reel_render_assets_reserves_logo_space_when_logo_matches_agent_photo(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            self._create_audio_asset(workspace_dir / "assets" / "music" / "test.mp3")
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            source_path = selected_dir / "primary_image.png"
            remote_agent_path = workspace_dir / "remote-agent.png"
            self._create_image(source_path, "800x600", "teal")
            self._create_image(remote_agent_path, "256x256", "white")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=(source_path,),
            )
            property_data.agent_photo_url = "https://cdn.example.com/team/AGENT-PORTRAIT.PNG?version=2"
            property_data.agency_logo_url = "https://example.com/branding/agent-portrait.png"
            template = PropertyReelTemplate(
                width=320,
                height=480,
                fps=12,
                max_slide_count=1,
                include_intro=False,
                intro_duration_seconds=0.0,
                total_duration_seconds=0.5,
                seconds_per_slide=0.5,
                subtitle_font_size=28,
                background_audio_filename="music/test.mp3",
            )
            download_calls: list[str] = []

            def fake_download(image_url: str, destination: Path) -> Path:
                download_calls.append(image_url)
                shutil.copyfile(remote_agent_path, destination)
                return destination

            with patch(
                "services.media.reel_rendering.runtime.download_remote_image",
                side_effect=fake_download,
            ):
                prepared_assets = prepare_reel_render_assets(
                    workspace_dir,
                    property_data,
                    template=template,
                    working_dir=workspace_dir / "_prepared_duplicate_logo",
                )

            self.assertEqual(download_calls, [property_data.agent_photo_url])
            self.assertIsNone(prepared_assets.cover_logo_path)
            self.assertTrue(prepared_assets.reserve_agency_logo_space)
            overlay_layout = build_overlay_layout(
                property_data,
                template,
                slides=tuple(
                    PropertyReelSlide(
                        image_path=prepared_slide.original_path,
                        caption=prepared_slide.caption,
                    )
                    for prepared_slide in prepared_assets.slides
                ),
                slide_duration=template.seconds_per_slide,
                has_ber_badge=False,
                has_agency_logo=prepared_assets.reserve_agency_logo_space,
                cover_caption=None,
            )
            self.assertIsNotNone(overlay_layout.agency_logo_box)

    def test_background_audio_candidates_are_shuffled_from_assets_music(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            music_dir = workspace_dir / "assets" / "music"
            self._create_audio_asset(music_dir / "a-track.mp3")
            self._create_audio_asset(music_dir / "b-track.mp3")
            self._create_audio_asset(music_dir / "c-track.mp3")
            template = PropertyReelTemplate(background_audio_filename="music/a-track.mp3")

            with patch("services.media.reel_rendering.runtime.random.SystemRandom") as system_random:
                system_random.return_value.shuffle.side_effect = lambda sequence: sequence.reverse()
                audio_candidates = resolve_background_audio_paths(
                    workspace_dir,
                    template,
                    shuffle_candidates=True,
                )

            self.assertEqual(
                tuple(path.name for path in audio_candidates),
                ("c-track.mp3", "b-track.mp3", "a-track.mp3"),
            )


class ReelRenderIntegrationTests(_FFmpegTestCase):
    def test_concat_command_reencodes_staged_segments_with_cfr_timeline(self) -> None:
        template = PropertyReelTemplate(
            width=320,
            height=480,
            fps=12,
            background_audio_filename="music/test.mp3",
        )

        command = _build_concat_command(
            ffmpeg_binary="ffmpeg",
            concat_list_path=Path("segments.txt"),
            settings=template,
            output_path=Path("out.mp4"),
        )

        self.assertIn("+genpts", command)
        self.assertIn("libx264", command)
        self.assertIn("fps=12,setpts=N/(12*TB),format=yuv420p", command)
        self.assertNotIn("copy", command)

    def test_generate_property_reel_from_data_renders_configured_resolution_and_fps(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            self._create_audio_asset(workspace_dir / "assets" / "music" / "test.mp3")
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            source_paths = [
                selected_dir / "primary_image.png",
                selected_dir / "01_living.png",
            ]
            self._create_image(source_paths[0], "1600x1000", "purple")
            self._create_image(source_paths[1], "900x1600", "orange")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=tuple(source_paths),
                price="650000",
                property_status="For Sale",
            )
            template = PropertyReelTemplate(
                width=320,
                height=480,
                fps=12,
                max_slide_count=2,
                include_intro=False,
                intro_duration_seconds=0.0,
                total_duration_seconds=1.0,
                seconds_per_slide=0.5,
                subtitle_font_size=28,
                background_audio_filename="music/test.mp3",
            )

            output_path = workspace_dir / "out.mp4"
            working_dir = workspace_dir / "_render"
            generate_property_reel_from_data(
                workspace_dir,
                property_data,
                output_path=output_path,
                template=template,
                working_dir=working_dir,
            )

            width, height, fps = self._probe_video_stream(output_path)
            self.assertEqual((width, height), (320, 480))
            self.assertEqual(fps, 12.0)
            self.assertTrue((working_dir / "segments" / "segment_01.mp4").exists())
            self.assertTrue((working_dir / "segments" / "segment_02.mp4").exists())

    def test_slide_segment_filter_accepts_apostrophes_with_logo_and_ber(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            output_path = workspace_dir / "segment.png"
            slide = PreparedReelSlide(
                original_path=workspace_dir / "source.jpg",
                working_path=workspace_dir / "slide.png",
                caption="Sunny southwesterly facing back garden with children's play area.",
                working_width=1340,
                working_height=1786,
                motion_mode="horizontal",
            )
            property_data = self._build_property_data(
                selected_dir=workspace_dir / "selected_photos",
                selected_paths=(),
                price="1395000",
                property_status="For Sale",
                banner_text="FOR SALE",
                price_display_text="€1,395,000",
            )
            property_data.title = "Chalain, 110 Roebuck Road, Clonskeagh, D14 K0T8"
            property_data.agent_name = "Phil Thompson"
            property_data.agent_email = "phil@ckp.ie"
            property_data.agent_number = "+353 1 288-3688"
            property_data.ber_rating = "B3"
            template = PropertyReelTemplate()
            filter_text = _build_slide_segment_filter(
                property_data=property_data,
                settings=template,
                slide=slide,
                slide_frames=120,
                slide_duration=5.0,
                include_agency_logo=True,
                include_ber_icon=True,
            )

            self._run_ffmpeg(
                [
                    self._ffmpeg_binary(),
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=1340x1786:d=5",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=122x122:d=5",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=white@0.0:s=173x75:d=5",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=green:s=300x97:d=5",
                    "-filter_complex",
                    filter_text,
                    "-map",
                    "[vout]",
                    "-frames:v",
                    "1",
                    str(output_path),
                ]
            )

            self.assertTrue(output_path.exists())

    def test_slide_segment_filter_reserves_logo_space_without_logo_overlay(self) -> None:
        slide = PreparedReelSlide(
            original_path=Path("source.jpg"),
            working_path=Path("slide.png"),
            caption="Bright living room",
            working_width=1340,
            working_height=1786,
            motion_mode="horizontal",
        )
        property_data = self._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(),
        )
        template = PropertyReelTemplate()

        filter_text = _build_slide_segment_filter(
            property_data=property_data,
            settings=template,
            slide=slide,
            slide_frames=120,
            slide_duration=5.0,
            include_agency_logo=True,
            include_ber_icon=False,
            render_agency_logo=False,
        )
        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(PropertyReelSlide(image_path=slide.working_path, caption=slide.caption),),
            slide_duration=5.0,
            has_ber_badge=False,
            has_agency_logo=True,
            cover_caption=None,
        )

        self.assertIsNotNone(overlay_layout.agency_logo_box)
        self.assertNotIn("[2:v]format=rgba[agency_logo]", filter_text)
        self.assertNotIn("[video_with_agent_panel][agency_logo]overlay=", filter_text)

    def test_slide_segment_filter_fits_agent_image_inside_box_without_backplate(self) -> None:
        slide = PreparedReelSlide(
            original_path=Path("source.jpg"),
            working_path=Path("slide.png"),
            caption="Bright living room",
            working_width=1340,
            working_height=1786,
            motion_mode="horizontal",
        )
        property_data = self._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(),
        )
        template = PropertyReelTemplate()
        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(PropertyReelSlide(image_path=slide.working_path, caption=slide.caption),),
            slide_duration=5.0,
            has_ber_badge=False,
            has_agency_logo=False,
            cover_caption=None,
        )
        assert overlay_layout.agent_image_box is not None

        filter_text = _build_slide_segment_filter(
            property_data=property_data,
            settings=template,
            slide=slide,
            slide_frames=120,
            slide_duration=5.0,
            include_agency_logo=False,
            include_ber_icon=False,
        )

        self.assertIn(
            (
                f"[1:v]scale=w={overlay_layout.agent_image_box.width}:h={overlay_layout.agent_image_box.height}:"
                f"force_original_aspect_ratio=decrease,pad={overlay_layout.agent_image_box.width}:"
                f"{overlay_layout.agent_image_box.height}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
                "format=rgba[agent_panel_image]"
            ),
            filter_text,
        )
        self.assertNotIn(
            f"crop={overlay_layout.agent_image_box.width}:{overlay_layout.agent_image_box.height}",
            filter_text,
        )
        self.assertNotIn("color=white@0.14:t=fill", filter_text)

    def test_first_slide_segment_filter_omits_fade_in(self) -> None:
        slide = PreparedReelSlide(
            original_path=Path("source.jpg"),
            working_path=Path("slide.png"),
            caption="Bright living room",
            working_width=1340,
            working_height=1786,
            motion_mode="horizontal",
        )
        property_data = self._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(),
        )
        template = PropertyReelTemplate()

        filter_text = _build_slide_segment_filter(
            property_data=property_data,
            settings=template,
            slide=slide,
            slide_frames=120,
            slide_duration=5.0,
            include_agency_logo=False,
            include_ber_icon=False,
            apply_fade_in=False,
        )

        self.assertNotIn("fade=t=in:st=0:d=", filter_text)
        self.assertIn("fade=t=out:st=", filter_text)

    def test_non_initial_slide_segment_filter_keeps_fade_in(self) -> None:
        slide = PreparedReelSlide(
            original_path=Path("source.jpg"),
            working_path=Path("slide.png"),
            caption="Bright living room",
            working_width=1340,
            working_height=1786,
            motion_mode="horizontal",
        )
        property_data = self._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(),
        )
        template = PropertyReelTemplate()

        filter_text = _build_slide_segment_filter(
            property_data=property_data,
            settings=template,
            slide=slide,
            slide_frames=120,
            slide_duration=5.0,
            include_agency_logo=False,
            include_ber_icon=False,
        )

        self.assertIn("fade=t=in:st=0:d=", filter_text)
        self.assertIn("fade=t=out:st=", filter_text)

    def test_generate_status_reel_uses_single_slide_without_intro(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            self._create_audio_asset(workspace_dir / "assets" / "music" / "test.mp3")
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            source_path = selected_dir / "primary_image.png"
            self._create_image(source_path, "1800x1200", "teal")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=(source_path,),
                price="",
                property_status="Sale Agreed",
                banner_text="SALE AGREED",
                price_display_text="",
            )
            template = build_reel_template_for_render_profile(
                "sale_agreed_status_reel",
                template=PropertyReelTemplate(
                    width=320,
                    height=480,
                    fps=12,
                    seconds_per_slide=0.5,
                    total_duration_seconds=0.5,
                    subtitle_font_size=28,
                    background_audio_filename="music/test.mp3",
                ),
            )

            output_path = workspace_dir / "status.mp4"
            working_dir = workspace_dir / "_status_render"
            generate_property_reel_from_data(
                workspace_dir,
                property_data,
                output_path=output_path,
                template=template,
                working_dir=working_dir,
            )

            width, height, fps = self._probe_video_stream(output_path)
            self.assertEqual((width, height), (320, 480))
            self.assertEqual(fps, 12.0)
            segment_files = sorted((working_dir / "segments").glob("*.mp4"))
            self.assertEqual(len(segment_files), 1)
            self.assertNotIn("segment_00_intro.mp4", {path.name for path in segment_files})

    def test_generate_property_reel_falls_back_to_next_audio_track(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            broken_audio_path = workspace_dir / "assets" / "music" / "broken.mp3"
            valid_audio_path = workspace_dir / "assets" / "music" / "fallback.mp3"
            broken_audio_path.parent.mkdir(parents=True, exist_ok=True)
            broken_audio_path.write_text("not-audio", encoding="utf-8")
            self._create_audio_asset(valid_audio_path)
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            source_path = selected_dir / "primary_image.png"
            self._create_image(source_path, "1800x1200", "teal")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=(source_path,),
            )
            template = PropertyReelTemplate(
                width=320,
                height=480,
                fps=12,
                max_slide_count=1,
                include_intro=False,
                intro_duration_seconds=0.0,
                total_duration_seconds=0.5,
                seconds_per_slide=0.5,
                subtitle_font_size=28,
                background_audio_filename="music/fallback.mp3",
            )
            prepared_assets = prepare_reel_render_assets(
                workspace_dir,
                property_data,
                template=template,
                working_dir=workspace_dir / "_prepared_reel",
            )
            prepared_assets.background_audio_candidates = (broken_audio_path, valid_audio_path)
            prepared_assets.background_audio_path = broken_audio_path
            output_path = workspace_dir / "fallback-reel.mp4"

            render_path = generate_property_reel_from_data(
                workspace_dir,
                property_data,
                output_path=output_path,
                template=template,
                prepared_assets=prepared_assets,
                working_dir=workspace_dir / "_render_reel",
            )

            self.assertEqual(render_path, output_path)
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)
            self.assertEqual(prepared_assets.background_audio_path, valid_audio_path)


class PosterRenderIntegrationTests(_FFmpegTestCase):
    def test_poster_photo_box_is_full_bleed_within_poster_bounds(self) -> None:
        property_data = self._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(Path("selected_photos/primary_image.png"),),
        )
        template = PropertyReelTemplate(
            width=360,
            height=640,
            max_slide_count=1,
            include_intro=False,
            intro_duration_seconds=0.0,
        )

        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(),
            slide_duration=None,
            has_ber_badge=False,
            has_agency_logo=True,
            cover_caption=None,
        )
        photo_box = _resolve_poster_photo_box(template, overlay_layout)

        self.assertEqual(photo_box.x, 0)
        self.assertEqual(photo_box.y, 0)
        self.assertEqual(photo_box.width, template.width)
        self.assertEqual(photo_box.height, template.height)

    def test_poster_filter_reserves_logo_space_without_logo_overlay(self) -> None:
        property_data = self._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(Path("selected_photos/primary_image.png"),),
        )
        template = PropertyReelTemplate(
            width=360,
            height=640,
            max_slide_count=1,
            include_intro=False,
            intro_duration_seconds=0.0,
        )
        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(),
            slide_duration=None,
            has_ber_badge=False,
            has_agency_logo=True,
            cover_caption=None,
        )
        filter_text = _build_poster_filter_script(
            property_data=property_data,
            settings=template,
            include_agency_logo=True,
            include_ber_icon=False,
            agent_input_index=1,
            agency_logo_input_index=None,
            ber_icon_input_index=None,
        )

        self.assertIsNotNone(overlay_layout.agency_logo_box)
        self.assertNotIn("[agency_logo]", filter_text)
        self.assertNotIn("video_with_agency_logo", filter_text)

    def test_poster_filter_fits_agent_image_inside_box_without_backplate(self) -> None:
        property_data = self._build_property_data(
            selected_dir=Path("selected_photos"),
            selected_paths=(Path("selected_photos/primary_image.png"),),
        )
        template = PropertyReelTemplate(
            width=720,
            height=1280,
            max_slide_count=1,
            include_intro=False,
            intro_duration_seconds=0.0,
        )
        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(),
            slide_duration=None,
            has_ber_badge=False,
            has_agency_logo=False,
            cover_caption=None,
        )
        assert overlay_layout.agent_image_box is not None

        filter_text = _build_poster_filter_script(
            property_data=property_data,
            settings=template,
            include_agency_logo=False,
            include_ber_icon=False,
            agent_input_index=1,
            agency_logo_input_index=None,
            ber_icon_input_index=None,
        )

        self.assertIn(
            (
                f"[1:v]scale=w={overlay_layout.agent_image_box.width}:h={overlay_layout.agent_image_box.height}:"
                f"force_original_aspect_ratio=decrease,pad={overlay_layout.agent_image_box.width}:"
                f"{overlay_layout.agent_image_box.height}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
                "format=rgba[agent_panel_image]"
            ),
            filter_text,
        )
        self.assertNotIn(
            f"[1:v]scale={overlay_layout.agent_image_box.width}:{overlay_layout.agent_image_box.height},format=rgba",
            filter_text,
        )
        self.assertNotIn("color=white@0.14:t=fill", filter_text)

    def test_generate_property_poster_from_data_uses_configured_output_resolution(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            self._create_audio_asset(workspace_dir / "assets" / "music" / "test.mp3")
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            source_path = selected_dir / "primary_image.png"
            self._create_image(source_path, "1500x900", "pink")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=(source_path,),
            )
            template = PropertyReelTemplate(
                width=360,
                height=640,
                fps=12,
                max_slide_count=1,
                include_intro=False,
                intro_duration_seconds=0.0,
                subtitle_font_size=26,
                background_audio_filename="music/test.mp3",
            )

            output_path = workspace_dir / "poster.jpg"
            generate_property_poster_from_data(
                workspace_dir,
                property_data,
                output_path=output_path,
                template=template,
            )

            self.assertEqual(self._probe_image_dimensions(output_path), (360, 640))

    def test_generate_property_poster_uses_original_cover_image_without_vertical_crop(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            original_path = selected_dir / "primary_image.png"
            working_path = selected_dir / "primary_image_vertical.png"
            agent_path = selected_dir / "agent.png"
            self._create_vertical_stripe_image(original_path, "1500x900")
            self._create_image(working_path, "900x1500", "magenta")
            self._create_image(agent_path, "400x400", "white")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=(original_path,),
            )
            template = PropertyReelTemplate(
                width=360,
                height=640,
                fps=12,
                max_slide_count=1,
                include_intro=False,
                intro_duration_seconds=0.0,
                subtitle_font_size=26,
            )
            prepared_assets = PreparedReelAssets(
                working_dir=workspace_dir / "_prepared_poster",
                slides=(
                    PreparedReelSlide(
                        original_path=original_path,
                        working_path=working_path,
                        caption=None,
                    ),
                ),
                cover_background_path=working_path,
                cover_logo_path=None,
                agent_image_path=agent_path,
                ber_icon_path=None,
                background_audio_path=workspace_dir / "unused.mp3",
            )
            output_path = workspace_dir / "poster-horizontal.jpg"

            with patch(
                "services.media.reel_rendering.poster.prepare_reel_render_assets",
                return_value=prepared_assets,
            ):
                generate_property_poster_from_data(
                    workspace_dir,
                    property_data,
                    output_path=output_path,
                    template=template,
                )

            overlay_layout = build_overlay_layout(
                property_data,
                template,
                slides=(),
                slide_duration=None,
                has_ber_badge=False,
                has_agency_logo=False,
                cover_caption=None,
            )
            photo_box = _resolve_poster_photo_box(template, overlay_layout)
            source_width, source_height = self._probe_image_dimensions(original_path)
            scale = min(photo_box.width / source_width, photo_box.height / source_height)
            rendered_width = max(1, round(source_width * scale))
            rendered_height = max(1, round(source_height * scale))
            rendered_x = photo_box.x + ((photo_box.width - rendered_width) // 2)
            rendered_y = photo_box.y + ((photo_box.height - rendered_height) // 2)
            sample_y = rendered_y + (rendered_height // 2)
            left_sample = self._sample_pixel_rgb(output_path, rendered_x + (rendered_width // 6), sample_y)
            center_sample = self._sample_pixel_rgb(output_path, rendered_x + (rendered_width // 2), sample_y)
            right_sample = self._sample_pixel_rgb(output_path, rendered_x + ((rendered_width * 5) // 6), sample_y)

            self.assertGreater(left_sample[0], 180)
            self.assertLess(left_sample[1], 100)
            self.assertLess(left_sample[2], 100)
            self.assertGreater(center_sample[1], 180)
            self.assertLess(center_sample[0], 100)
            self.assertLess(center_sample[2], 100)
            self.assertGreater(right_sample[2], 180)
            self.assertLess(right_sample[0], 100)
            self.assertLess(right_sample[1], 100)


class ReelManifestPreparedAssetTests(_FFmpegTestCase):
    def test_manifest_records_prepared_working_assets(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            self._create_audio_asset(workspace_dir / "assets" / "music" / "test.mp3")
            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            source_paths = [
                selected_dir / "primary_image.png",
                selected_dir / "01_living.png",
            ]
            self._create_image(source_paths[0], "1800x1200", "navy")
            self._create_image(source_paths[1], "1200x1800", "lime")

            property_data = self._build_property_data(
                selected_dir=selected_dir,
                selected_paths=tuple(source_paths),
            )
            template = PropertyReelTemplate(
                width=320,
                height=480,
                fps=12,
                max_slide_count=2,
                include_intro=False,
                intro_duration_seconds=0.0,
                total_duration_seconds=1.0,
                seconds_per_slide=0.5,
                subtitle_font_size=28,
                background_audio_filename="music/test.mp3",
            )
            prepared_assets = prepare_reel_render_assets(
                workspace_dir,
                property_data,
                template=template,
                working_dir=workspace_dir / "_prepared_manifest",
            )

            manifest = build_property_reel_manifest_from_data(
                workspace_dir,
                property_data,
                template=template,
                prepared_assets=prepared_assets,
                working_dir=workspace_dir / "_prepared_manifest",
            )

            self.assertEqual(manifest["slide_count"], 2)
            self.assertEqual(manifest["segment_count"], 2)
            self.assertIn("render_settings", manifest)
            self.assertEqual(manifest["render_settings"]["width"], 320)
            self.assertEqual(manifest["render_settings"]["height"], 480)
            self.assertEqual(manifest["render_settings"]["footer_bottom_offset_px"], 0)
            self.assertIsNotNone(manifest["prepared_assets"])
            prepared_manifest = manifest["prepared_assets"]
            assert prepared_manifest is not None
            self.assertEqual(len(prepared_manifest["slides"]), 2)
            self.assertEqual(
                prepared_manifest["slides"][0]["original_image_path"],
                str(source_paths[0]),
            )
            self.assertTrue(
                prepared_manifest["slides"][0]["working_image_path"].endswith("slide_01.png")
            )
            self.assertIsNotNone(prepared_manifest["slides"][0]["working_resolution"])
            self.assertIn(
                prepared_manifest["slides"][0]["motion_mode"],
                {"horizontal"},
            )


if __name__ == "__main__":
    unittest.main()
