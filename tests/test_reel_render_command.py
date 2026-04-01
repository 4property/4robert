from __future__ import annotations

import sys
import unittest
from pathlib import Path

APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from services.reel_rendering.models import PropertyReelTemplate
from services.reel_rendering.render import _build_ffmpeg_reel_command


class ReelRenderCommandTests(unittest.TestCase):
    def _build_command(self, *, settings: PropertyReelTemplate) -> list[str]:
        return _build_ffmpeg_reel_command(
            ffmpeg_binary="ffmpeg",
            slide_image_paths=[Path("slide-1.jpg"), Path("slide-2.jpg")],
            slide_duration=5.0,
            total_duration=13.0,
            settings=settings,
            logo_path=Path("logo.png"),
            agent_image_path=Path("agent.png"),
            ber_icon_path=Path("ber.png"),
            background_audio_path=Path("music.mp3"),
            filter_script_path=Path("filter_complex.txt"),
            output_path=Path("out.mp4"),
            audio_fade_start=11.5,
            audio_fade_duration=1.5,
        )

    def test_default_command_limits_filter_and_encoder_threads(self) -> None:
        settings = PropertyReelTemplate()

        command = self._build_command(settings=settings)

        self.assertIn("-filter_complex_threads", command)
        self.assertEqual(
            command[command.index("-filter_complex_threads") + 1],
            str(settings.ffmpeg_filter_threads),
        )
        self.assertIn("-threads:v", command)
        self.assertEqual(
            command[command.index("-threads:v") + 1],
            str(settings.ffmpeg_encoder_threads),
        )

    def test_zero_thread_settings_leave_ffmpeg_thread_defaults_untouched(self) -> None:
        settings = PropertyReelTemplate(
            ffmpeg_filter_threads=0,
            ffmpeg_encoder_threads=0,
        )

        command = self._build_command(settings=settings)

        self.assertNotIn("-filter_complex_threads", command)
        self.assertNotIn("-threads:v", command)


if __name__ == "__main__":
    unittest.main()
