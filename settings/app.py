from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, ValidationError as PydanticValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from core.errors import ApplicationError
from settings.database import (
    DEFAULT_DATABASE_ENCRYPTION_KEY,
    DEFAULT_DATABASE_MAX_OVERFLOW,
    DEFAULT_DATABASE_POOL_SIZE,
    DEFAULT_DATABASE_POOL_TIMEOUT_SECONDS,
    DEFAULT_DATABASE_URL,
)


def _parse_key_value_mapping(value: str | dict[str, str] | None) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(site_id): str(mapped_value) for site_id, mapped_value in value.items()}

    site_mapping: dict[str, str] = {}
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry or "=" not in entry:
            continue
        site_id, mapped_value = entry.split("=", 1)
        site_id = site_id.strip()
        mapped_value = mapped_value.strip()
        if site_id and mapped_value:
            site_mapping[site_id] = mapped_value
    return site_mapping


def _parse_platforms(
    value: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if value is None:
        return ()

    raw_values: list[str] = []
    if isinstance(value, str):
        raw_values.extend(part.strip() for part in value.split(","))
    else:
        raw_values.extend(str(part).strip() for part in value)

    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        normalized_value = raw_value.strip().lower()
        if not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized_values.append(normalized_value)
    return tuple(normalized_values)


def _parse_csv_values(
    value: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if value is None:
        return ()

    raw_values: list[str] = []
    if isinstance(value, str):
        raw_values.extend(part.strip() for part in value.split(","))
    else:
        raw_values.extend(str(part).strip() for part in value)

    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        normalized_value = raw_value.strip()
        if not normalized_value:
            continue
        lowered = normalized_value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized_values.append(normalized_value)
    return tuple(normalized_values)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    outbound_http_timeout_seconds: int = Field(
        30,
        validation_alias="OUTBOUND_HTTP_TIMEOUT_SECONDS",
        ge=1,
    )

    webhook_host: str = Field(
        "127.0.0.1",
        validation_alias="WEBHOOK_HOST",
    )
    webhook_port: int = Field(
        8000,
        validation_alias="WEBHOOK_PORT",
        ge=1,
    )
    webhook_path: str = Field(
        "/webhooks/wordpress/property",
        validation_alias="WEBHOOK_PATH",
    )
    webhook_site_id_header: str = Field(
        "X-WordPress-Site-ID",
        validation_alias="WEBHOOK_SITE_ID_HEADER",
    )
    webhook_timestamp_header: str = Field(
        "X-WordPress-Timestamp",
        validation_alias="WEBHOOK_TIMESTAMP_HEADER",
    )
    webhook_signature_header: str = Field(
        "X-WordPress-Signature",
        validation_alias="WEBHOOK_SIGNATURE_HEADER",
    )
    webhook_gohighlevel_location_id_header: str = Field(
        "X-GoHighLevel-Location-ID",
        validation_alias="WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER",
    )
    webhook_gohighlevel_access_token_header: str = Field(
        "X-GoHighLevel-Access-Token",
        validation_alias="WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER",
    )
    webhook_disable_security: bool = Field(
        False,
        validation_alias="WEBHOOK_DISABLE_SECURITY",
    )
    webhook_enable_docs: bool = Field(
        False,
        validation_alias="WEBHOOK_ENABLE_DOCS",
    )
    webhook_worker_count: int = Field(
        1,
        validation_alias="WEBHOOK_WORKER_COUNT",
        ge=1,
    )
    webhook_job_max_attempts: int = Field(
        3,
        validation_alias="WEBHOOK_JOB_MAX_ATTEMPTS",
        ge=1,
    )
    webhook_job_retry_backoff_seconds: float = Field(
        30.0,
        validation_alias="WEBHOOK_JOB_RETRY_BACKOFF_SECONDS",
        ge=0.0,
    )
    webhook_queue_poll_interval_seconds: float = Field(
        0.5,
        validation_alias="WEBHOOK_QUEUE_POLL_INTERVAL_SECONDS",
        gt=0.0,
    )
    webhook_queue_lease_seconds: int = Field(
        900,
        validation_alias="WEBHOOK_QUEUE_LEASE_SECONDS",
        ge=30,
    )
    webhook_shutdown_timeout_seconds: int = Field(
        10,
        validation_alias="WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS",
        ge=1,
    )
    webhook_timestamp_tolerance_seconds: int = Field(
        300,
        validation_alias="WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS",
        ge=1,
    )
    webhook_max_payload_bytes: int = Field(
        1_000_000,
        validation_alias="WEBHOOK_MAX_PAYLOAD_BYTES",
        ge=1,
    )
    webhook_site_secrets: dict[str, str] | str | None = Field(
        None,
        validation_alias="WEBHOOK_SITE_SECRETS",
    )
    webhook_allowed_hosts: Annotated[tuple[str, ...], NoDecode] = Field(
        (),
        validation_alias="WEBHOOK_ALLOWED_HOSTS",
    )
    webhook_trust_proxy_headers: bool = Field(
        True,
        validation_alias="WEBHOOK_TRUST_PROXY_HEADERS",
    )
    webhook_forwarded_allow_ips: str = Field(
        "127.0.0.1",
        validation_alias="WEBHOOK_FORWARDED_ALLOW_IPS",
    )
    webhook_limit_concurrency: int = Field(
        64,
        validation_alias="WEBHOOK_LIMIT_CONCURRENCY",
        ge=1,
    )
    database_url: str = Field(
        DEFAULT_DATABASE_URL,
        validation_alias="DATABASE_URL",
    )
    database_pool_size: int = Field(
        DEFAULT_DATABASE_POOL_SIZE,
        validation_alias="DATABASE_POOL_SIZE",
        ge=1,
    )
    database_max_overflow: int = Field(
        DEFAULT_DATABASE_MAX_OVERFLOW,
        validation_alias="DATABASE_MAX_OVERFLOW",
        ge=0,
    )
    database_pool_timeout_seconds: int = Field(
        DEFAULT_DATABASE_POOL_TIMEOUT_SECONDS,
        validation_alias="DATABASE_POOL_TIMEOUT_SECONDS",
        ge=1,
    )
    database_encryption_key: str = Field(
        DEFAULT_DATABASE_ENCRYPTION_KEY,
        validation_alias="DATABASE_ENCRYPTION_KEY",
    )
    go_high_level_base_url: str = Field(
        "https://services.leadconnectorhq.com",
        validation_alias="GO_HIGH_LEVEL_BASE_URL",
    )
    go_high_level_api_version: str = Field(
        "2021-07-28",
        validation_alias="GO_HIGH_LEVEL_API_VERSION",
    )
    social_publishing_default_platforms: Annotated[tuple[str, ...], NoDecode] = Field(
        (
            "tiktok",
            "instagram",
            "linkedin",
            "youtube",
            "facebook",
            "google_business_profile",
        ),
        validation_alias=AliasChoices(
            "SOCIAL_PUBLISHING_DEFAULT_PLATFORMS",
            "SOCIAL_PUBLISHING_DEFAULT_PLATFORM",
        ),
    )
    social_publishing_enabled: bool = Field(
        True,
        validation_alias="SOCIAL_PUBLISHING_ENABLED",
    )
    social_publishing_local_only: bool = Field(
        False,
        validation_alias="SOCIAL_PUBLISHING_LOCAL_ONLY",
    )
    social_publishing_property_url_template: str = Field(
        "https://{site_id}/property/{slug}",
        validation_alias="SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE",
    )
    social_publishing_property_url_tracking_params: dict[str, str] | str | None = Field(
        None,
        validation_alias="SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS",
    )
    social_publishing_retry_attempts: int = Field(
        3,
        validation_alias="SOCIAL_PUBLISHING_RETRY_ATTEMPTS",
        ge=1,
    )
    social_publishing_retry_backoff_seconds: float = Field(
        1.5,
        validation_alias="SOCIAL_PUBLISHING_RETRY_BACKOFF_SECONDS",
        ge=0.0,
    )
    social_publishing_youtube_post_type: str = Field(
        "post",
        validation_alias="SOCIAL_PUBLISHING_YOUTUBE_POST_TYPE",
    )
    social_publishing_post_status_poll_attempts: int = Field(
        10,
        validation_alias="SOCIAL_PUBLISHING_POST_STATUS_POLL_ATTEMPTS",
        ge=1,
    )
    social_publishing_post_status_poll_interval_seconds: float = Field(
        3.0,
        validation_alias="SOCIAL_PUBLISHING_POST_STATUS_POLL_INTERVAL_SECONDS",
        ge=0.0,
    )
    property_media_delete_temporary_files: bool = Field(
        True,
        validation_alias="PROPERTY_MEDIA_DELETE_TEMPORARY_FILES",
    )
    property_media_delete_selected_photos: bool = Field(
        False,
        validation_alias="PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS",
    )
    reel_total_duration_seconds: float = Field(
        35.0,
        validation_alias="REEL_TOTAL_DURATION_SECONDS",
        gt=0.0,
    )
    reel_seconds_per_slide: float = Field(
        5.0,
        validation_alias="REEL_SECONDS_PER_SLIDE",
        gt=0.0,
    )
    reel_intro_duration_seconds: float = Field(
        0.0,
        validation_alias="REEL_INTRO_DURATION_SECONDS",
        ge=0.0,
    )
    reel_width: int = Field(
        1080,
        validation_alias="REEL_WIDTH",
        ge=2,
    )
    reel_height: int = Field(
        1440,
        validation_alias="REEL_HEIGHT",
        ge=2,
    )
    reel_fps: int = Field(
        24,
        validation_alias="REEL_FPS",
        ge=1,
    )
    poster_width: int = Field(
        1080,
        validation_alias="POSTER_WIDTH",
        ge=2,
    )
    poster_height: int = Field(
        1920,
        validation_alias="POSTER_HEIGHT",
        ge=2,
    )
    poster_background_blur_radius: int = Field(
        36,
        validation_alias="POSTER_BACKGROUND_BLUR_RADIUS",
        ge=0,
    )
    poster_background_blur_power: int = Field(
        12,
        validation_alias="POSTER_BACKGROUND_BLUR_POWER",
        ge=0,
    )
    poster_photo_side_margin_ratio: float = Field(
        0.06,
        validation_alias="POSTER_PHOTO_SIDE_MARGIN_RATIO",
        ge=0.0,
    )
    poster_photo_side_margin_min_px: int = Field(
        24,
        validation_alias="POSTER_PHOTO_SIDE_MARGIN_MIN_PX",
        ge=0,
    )
    poster_photo_panel_gap_ratio: float = Field(
        0.016,
        validation_alias="POSTER_PHOTO_PANEL_GAP_RATIO",
        ge=0.0,
    )
    poster_photo_panel_gap_min_px: int = Field(
        16,
        validation_alias="POSTER_PHOTO_PANEL_GAP_MIN_PX",
        ge=0,
    )
    poster_footer_bottom_offset_px: int = Field(
        56,
        validation_alias="POSTER_FOOTER_BOTTOM_OFFSET_PX",
        ge=0,
    )
    reel_subtitle_font_path: str = Field(
        "assets/fonts/Inter/static/Inter_28pt-Bold.ttf",
        validation_alias="REEL_SUBTITLE_FONT_PATH",
    )
    reel_subtitle_font_size: int = Field(
        54,
        validation_alias="REEL_SUBTITLE_FONT_SIZE",
        ge=1,
    )
    reel_ffmpeg_filter_threads: int = Field(
        1,
        validation_alias="REEL_FFMPEG_FILTER_THREADS",
        ge=0,
    )
    reel_ffmpeg_encoder_threads: int = Field(
        2,
        validation_alias="REEL_FFMPEG_ENCODER_THREADS",
        ge=0,
    )
    reel_ber_icon_scale: float = Field(
        0.5,
        validation_alias="REEL_BER_ICON_SCALE",
        gt=0.0,
    )
    reel_agency_logo_scale: float = Field(
        1.5,
        validation_alias="REEL_AGENCY_LOGO_SCALE",
        gt=0.0,
    )
    gemini_api_key: str = Field(
        "",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GEMINI_KEY"),
    )
    gemini_model: str = Field(
        "gemini-2.5-flash",
        validation_alias="GEMINI_MODEL",
    )
    gemini_timeout_seconds: int = Field(
        90,
        validation_alias="GEMINI_TIMEOUT_SECONDS",
        ge=1,
    )
    gemini_retry_attempts: int = Field(
        6,
        validation_alias="GEMINI_RETRY_ATTEMPTS",
        ge=1,
    )
    review_workflow_enabled: bool = Field(
        False,
        validation_alias="REVIEW_WORKFLOW_ENABLED",
    )
    notifications_enabled: bool = Field(
        False,
        validation_alias="NOTIFICATIONS_ENABLED",
    )
    ai_copy_enabled: bool = Field(
        False,
        validation_alias="AI_COPY_ENABLED",
    )
    ai_narration_enabled: bool = Field(
        False,
        validation_alias="AI_NARRATION_ENABLED",
    )
    persistent_logging_enabled: bool = Field(
        True,
        validation_alias="PERSISTENT_LOGGING_ENABLED",
    )
    persistent_log_directory: str = Field(
        "logs",
        validation_alias="PERSISTENT_LOG_DIRECTORY",
    )
    persistent_log_max_bytes: int = Field(
        25_000_000,
        validation_alias="PERSISTENT_LOG_MAX_BYTES",
        ge=1_024,
    )
    persistent_log_backup_count: int = Field(
        20,
        validation_alias="PERSISTENT_LOG_BACKUP_COUNT",
        ge=1,
    )
    log_level: str = Field(
        "INFO",
        validation_alias="LOG_LEVEL",
    )

    @field_validator("webhook_site_secrets", mode="before")
    @classmethod
    def _validate_site_secrets(cls, value: object) -> dict[str, str]:
        if value is None or isinstance(value, (str, dict)):
            return _parse_key_value_mapping(value)
        return {}

    @field_validator("social_publishing_property_url_tracking_params", mode="before")
    @classmethod
    def _validate_social_tracking_params(cls, value: object) -> dict[str, str]:
        if value is None or isinstance(value, (str, dict)):
            return _parse_key_value_mapping(value)
        return {}

    @field_validator("social_publishing_default_platforms", mode="before")
    @classmethod
    def _validate_social_platforms(cls, value: object) -> tuple[str, ...]:
        if value is None or isinstance(value, (str, list, tuple)):
            return _parse_platforms(value)
        return ()

    @field_validator("webhook_allowed_hosts", mode="before")
    @classmethod
    def _validate_webhook_allowed_hosts(cls, value: object) -> tuple[str, ...]:
        if value is None or isinstance(value, (str, list, tuple)):
            return _parse_csv_values(value)
        return ()

    @field_validator("webhook_path")
    @classmethod
    def _validate_webhook_path(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("WEBHOOK_PATH cannot be empty.")
        if not normalized_value.startswith("/"):
            raise ValueError("WEBHOOK_PATH must start with '/'.")
        return normalized_value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized_value = value.strip().upper()
        if not normalized_value:
            return "INFO"
        return normalized_value

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("DATABASE_URL cannot be empty.")
        if "postgresql" not in normalized_value:
            raise ValueError("DATABASE_URL must point to PostgreSQL.")
        return normalized_value

    @field_validator("database_encryption_key")
    @classmethod
    def _validate_database_encryption_key(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("DATABASE_ENCRYPTION_KEY cannot be empty.")
        return normalized_value

    @field_validator("persistent_log_directory")
    @classmethod
    def _validate_persistent_log_directory(cls, value: str) -> str:
        normalized_value = value.strip().strip("/\\")
        if not normalized_value:
            return "logs"
        return normalized_value

    @field_validator("webhook_forwarded_allow_ips")
    @classmethod
    def _validate_forwarded_allow_ips(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            return "127.0.0.1"
        return normalized_value

    @model_validator(mode="after")
    def _apply_defaults(self) -> "AppSettings":
        if not self.webhook_site_secrets:
            self.webhook_site_secrets = {}

        if not self.log_level:
            self.log_level = "INFO"

        if not self.persistent_log_directory:
            self.persistent_log_directory = "logs"

        if self.social_publishing_property_url_tracking_params is None:
            self.social_publishing_property_url_tracking_params = {}

        if not self.social_publishing_default_platforms:
            self.social_publishing_default_platforms = (
                "tiktok",
                "instagram",
                "linkedin",
                "youtube",
                "facebook",
                "google_business_profile",
            )

        self.social_publishing_youtube_post_type = (
            self.social_publishing_youtube_post_type.strip().lower() or "post"
        )

        return self


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    try:
        return AppSettings()
    except PydanticValidationError as exc:
        env_file_path = Path(".env").resolve()
        issues: list[str] = []
        context: dict[str, object] = {
            "env_file": str(env_file_path),
            "issue_count": len(exc.errors()),
        }
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg") or "Invalid value")
            rendered_issue = f"{location}: {message}" if location else message
            issues.append(rendered_issue)
        raise ApplicationError(
            "Invalid runtime configuration. " + "; ".join(issues),
            context=context,
            hint=(
                "Review the values in .env against .env.example. On Rocky Linux, validate the "
                "environment first with `python main.py --check` before starting the systemd service."
            ),
            cause=exc,
        ) from exc


APP_SETTINGS = get_app_settings()


__all__ = ["APP_SETTINGS", "AppSettings", "get_app_settings"]
