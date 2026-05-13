"""Pydantic payloads for the agency automation-rules endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AutomationRulesUpsertPayload(BaseModel):
    """Body for `PUT /v1/admin/agencies/{agency_id}/automation`.

    Automation rules persist to `agency_automation_rules`. `platforms` is
    intentionally NOT accepted here — the canonical owner is
    `agency_reel_defaults` (the `/defaults` endpoint).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "approval_required": False,
                "publish_window_start": "09:00",
                "publish_window_end": "20:00",
                "publish_days": ["mon", "tue", "wed", "thu", "fri"],
                "trigger_on_status": ["for_sale", "to_let"],
                "hold_window_seconds": 0,
                "quiet_hours_enabled": False,
                "skip_weekends": False,
            }
        },
    )

    approval_required: bool | None = Field(
        default=None,
        description=(
            "When true, reels are parked in `awaiting_review` until a "
            "human approves them; when false, the pipeline auto-publishes."
        ),
    )
    publish_window_start: str | None = Field(
        default=None,
        description="Earliest publish time of day, in `HH:MM` (24h, agency timezone).",
        examples=["09:00"],
    )
    publish_window_end: str | None = Field(
        default=None,
        description="Latest publish time of day, in `HH:MM` (24h, agency timezone).",
        examples=["20:00"],
    )
    publish_days: list[str] | None = Field(
        default=None,
        description="Three-letter lowercase weekdays when auto-publish runs.",
        examples=[["mon", "tue", "wed", "thu", "fri"]],
    )
    trigger_on_status: list[str] | None = Field(
        default=None,
        description="Property statuses that trigger reel generation.",
        examples=[["for_sale", "to_let"]],
    )
    hold_window_seconds: int | None = Field(
        default=None,
        ge=0,
        le=86400,
        description=(
            "Delay in seconds to wait before publishing after the trigger "
            "(0 = immediate, max 24h)."
        ),
    )
    quiet_hours_enabled: bool | None = Field(
        default=None,
        description=(
            "When true, publishes are deferred until publish_window_start "
            "if outside [start, end]."
        ),
    )
    skip_weekends: bool | None = Field(
        default=None,
        description=(
            "When true, publishes scheduled for Saturday/Sunday are deferred "
            "to the next Monday."
        ),
    )


__all__ = ["AutomationRulesUpsertPayload"]
