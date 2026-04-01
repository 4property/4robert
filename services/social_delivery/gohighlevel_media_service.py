from __future__ import annotations

import mimetypes
from pathlib import Path

from core.errors import ResourceNotFoundError, SocialPublishingError, ValidationError
from services.social_delivery.gohighlevel_client import GoHighLevelClient
from services.social_delivery.models import UploadedMedia

MAX_GHL_GENERAL_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_GHL_VIDEO_UPLOAD_BYTES = 500 * 1024 * 1024


class GoHighLevelMediaService:
    def __init__(self, *, client: GoHighLevelClient) -> None:
        self.client = client

    def upload_media(
        self,
        *,
        access_token: str,
        media_path: str | Path,
        upload_file_name: str | None = None,
    ) -> UploadedMedia:
        resolved_path = Path(media_path).expanduser().resolve()
        if not resolved_path.exists():
            raise ResourceNotFoundError(
                "The media file to upload was not found.",
                context={"media_path": str(resolved_path)},
                hint=(
                    "Verify the render completed successfully and that the deployed service can read the "
                    "generated_media directory."
                ),
            )
        if not resolved_path.is_file():
            raise ValidationError(
                "The media upload path is not a file.",
                context={"media_path": str(resolved_path)},
                hint="Check the configured artifact path and ensure it points to a regular file.",
            )

        mime_type = mimetypes.guess_type(resolved_path.name)[0] or "application/octet-stream"
        self._validate_media_file(resolved_path, mime_type=mime_type)
        requested_upload_name = self._resolve_upload_file_name(
            resolved_path=resolved_path,
            upload_file_name=upload_file_name,
        )

        with resolved_path.open("rb") as file_handle:
            payload = self.client.request_json(
                "POST",
                "/medias/upload-file",
                access_token=access_token,
                data={
                    "hosted": "false",
                    "name": requested_upload_name,
                },
                files={
                    "file": (requested_upload_name, file_handle, mime_type),
                },
            )

        file_id = payload.get("fileId")
        url = payload.get("url")
        if not isinstance(file_id, str) or not file_id.strip():
            raise SocialPublishingError(
                "GoHighLevel media upload succeeded without a fileId.",
                hint="Inspect the raw API response and verify the media upload endpoint still returns fileId.",
            )
        if not isinstance(url, str) or not url.strip():
            raise SocialPublishingError(
                "GoHighLevel media upload succeeded without a media URL.",
                hint="Inspect the raw API response and verify the media upload endpoint still returns url.",
            )

        return UploadedMedia(
            file_id=file_id.strip(),
            url=url.strip(),
            mime_type=mime_type,
            file_name=requested_upload_name,
            raw_response=payload,
        )

    def upload_video(self, *, access_token: str, video_path: str | Path) -> UploadedMedia:
        return self.upload_media(access_token=access_token, media_path=video_path)

    @staticmethod
    def _resolve_upload_file_name(
        *,
        resolved_path: Path,
        upload_file_name: str | None,
    ) -> str:
        normalized_name = str(upload_file_name or "").strip()
        if not normalized_name:
            return resolved_path.name

        safe_stem = (
            normalized_name.replace("\\", " ")
            .replace("/", " ")
            .replace(":", " ")
            .replace("*", " ")
            .replace("?", "")
            .replace('"', "")
            .replace("<", "")
            .replace(">", "")
            .replace("|", "")
        ).strip()
        if not safe_stem:
            return resolved_path.name

        suffix = resolved_path.suffix or ""
        if safe_stem.lower().endswith(suffix.lower()) and suffix:
            return safe_stem
        return f"{safe_stem}{suffix}"

    @staticmethod
    def _validate_media_file(resolved_path: Path, *, mime_type: str) -> None:
        file_size = resolved_path.stat().st_size
        if file_size <= 0:
            raise ValidationError(
                "The media file is empty.",
                context={"media_path": str(resolved_path)},
                hint="Check the render logs and confirm ffmpeg produced a non-empty output file.",
            )

        if mime_type.startswith("video/"):
            if file_size > MAX_GHL_VIDEO_UPLOAD_BYTES:
                raise ValidationError(
                    f"Video file exceeds the GoHighLevel upload limit of {MAX_GHL_VIDEO_UPLOAD_BYTES} bytes.",
                    context={"media_path": str(resolved_path), "file_size_bytes": file_size},
                    hint="Lower the render bitrate or duration before retrying the social publish.",
                )
            return

        if file_size > MAX_GHL_GENERAL_UPLOAD_BYTES:
            raise ValidationError(
                f"Media file exceeds the GoHighLevel upload limit of {MAX_GHL_GENERAL_UPLOAD_BYTES} bytes.",
                context={"media_path": str(resolved_path), "file_size_bytes": file_size},
                hint="Reduce the media size before retrying the social publish.",
            )


__all__ = [
    "GoHighLevelMediaService",
    "MAX_GHL_GENERAL_UPLOAD_BYTES",
    "MAX_GHL_VIDEO_UPLOAD_BYTES",
]
