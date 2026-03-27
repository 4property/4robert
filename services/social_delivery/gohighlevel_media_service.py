from __future__ import annotations

import mimetypes
from pathlib import Path

from core.errors import ResourceNotFoundError, SocialPublishingError, ValidationError
from services.social_delivery.gohighlevel_client import GoHighLevelClient
from services.social_delivery.models import UploadedMedia

MAX_GHL_VIDEO_UPLOAD_BYTES = 500 * 1024 * 1024


class GoHighLevelMediaService:
    def __init__(self, *, client: GoHighLevelClient) -> None:
        self.client = client

    def upload_video(self, *, access_token: str, video_path: str | Path) -> UploadedMedia:
        resolved_path = Path(video_path).expanduser().resolve()
        if not resolved_path.exists():
            raise ResourceNotFoundError(f"Video file does not exist: {resolved_path}")
        if not resolved_path.is_file():
            raise ValidationError(f"Video path is not a file: {resolved_path}")

        file_size = resolved_path.stat().st_size
        if file_size <= 0:
            raise ValidationError(f"Video file is empty: {resolved_path}")
        if file_size > MAX_GHL_VIDEO_UPLOAD_BYTES:
            raise ValidationError(
                f"Video file exceeds the GoHighLevel upload limit of {MAX_GHL_VIDEO_UPLOAD_BYTES} bytes."
            )

        mime_type = mimetypes.guess_type(resolved_path.name)[0] or "video/mp4"
        with resolved_path.open("rb") as file_handle:
            payload = self.client.request_json(
                "POST",
                "/medias/upload-file",
                access_token=access_token,
                data={
                    "hosted": "false",
                    "name": resolved_path.name,
                },
                files={
                    "file": (resolved_path.name, file_handle, mime_type),
                },
            )

        file_id = payload.get("fileId")
        url = payload.get("url")
        if not isinstance(file_id, str) or not file_id.strip():
            raise SocialPublishingError("GoHighLevel media upload succeeded without a fileId.")
        if not isinstance(url, str) or not url.strip():
            raise SocialPublishingError("GoHighLevel media upload succeeded without a media URL.")

        return UploadedMedia(
            file_id=file_id.strip(),
            url=url.strip(),
            mime_type=mime_type,
            file_name=resolved_path.name,
            raw_response=payload,
        )


__all__ = ["GoHighLevelMediaService", "MAX_GHL_VIDEO_UPLOAD_BYTES"]

