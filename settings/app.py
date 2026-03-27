from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _infer_legacy_site_id(default_link: str) -> str:
    parsed = urlparse(default_link)
    return parsed.netloc or "legacy-site"


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


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    wordpress_link: str = Field(
        "https://example-estate.ie/wp-json/wp/v2/property",
        validation_alias="WORDPRESS_LINK",
    )
    wordpress_per_page: int = Field(
        100,
        validation_alias="WORDPRESS_PER_PAGE",
        ge=1,
    )
    request_timeout_seconds: int = Field(
        30,
        validation_alias="REQUEST_TIMEOUT_SECONDS",
        ge=1,
    )

    legacy_site_id: str | None = Field(
        None,
        validation_alias="LEGACY_SITE_ID",
    )
    webhook_host: str = Field(
        "0.0.0.0",
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
    sqlite_busy_timeout_ms: int = Field(
        5_000,
        validation_alias="SQLITE_BUSY_TIMEOUT_MS",
        ge=1,
    )
    go_high_level_base_url: str = Field(
        "https://services.leadconnectorhq.com",
        validation_alias="GO_HIGH_LEVEL_BASE_URL",
    )
    go_high_level_api_version: str = Field(
        "2021-07-28",
        validation_alias="GO_HIGH_LEVEL_API_VERSION",
    )
    social_publishing_default_platform: str = Field(
        "tiktok",
        validation_alias="SOCIAL_PUBLISHING_DEFAULT_PLATFORM",
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
    reel_total_duration_seconds: float = Field(
        43.0,
        validation_alias="REEL_TOTAL_DURATION_SECONDS",
        gt=0.0,
    )
    reel_seconds_per_slide: float = Field(
        5.0,
        validation_alias="REEL_SECONDS_PER_SLIDE",
        gt=0.0,
    )
    reel_intro_duration_seconds: float = Field(
        3.0,
        validation_alias="REEL_INTRO_DURATION_SECONDS",
        ge=0.0,
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

    @model_validator(mode="after")
    def _apply_defaults(self) -> "AppSettings":
        if not self.legacy_site_id:
            self.legacy_site_id = _infer_legacy_site_id(self.wordpress_link)

        if not self.webhook_site_secrets:
            self.webhook_site_secrets = {self.legacy_site_id: "change-me"}

        if not self.log_level:
            self.log_level = "INFO"

        if self.social_publishing_property_url_tracking_params is None:
            self.social_publishing_property_url_tracking_params = {}

        return self


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()


APP_SETTINGS = get_app_settings()


__all__ = ["APP_SETTINGS", "AppSettings", "get_app_settings"]
