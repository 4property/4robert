from __future__ import annotations

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base


class RenderTemplateORM(Base):
    __tablename__ = "render_templates"

    template_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    preview_images: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    layout_variant: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="classic"
    )
    reel_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    poster_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgencyBrandSettingsORM(Base):
    __tablename__ = "agency_brand_settings"

    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    primary_color: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="#0F172A"
    )
    secondary_color: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="#FFFFFF"
    )
    logo_position: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="top-right"
    )
    logo_object_key: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    intro_logo_object_key: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    font_family: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgencyReelDefaultsORM(Base):
    __tablename__ = "agency_reel_defaults"

    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    platforms: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text(
            "ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp',"
            "'pinterest']::text[]"
        ),
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30"
    )
    music_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    intro_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE")
    )
    caption_template: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    render_template_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("render_templates.template_id"),
        nullable=False,
        server_default="classic",
    )
    settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgencyAutomationRulesORM(Base):
    __tablename__ = "agency_automation_rules"

    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    publish_window_start: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    publish_window_end: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    publish_days: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY[]::text[]")
    )
    trigger_on_status: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['published']::text[]"),
    )
    hold_window_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    skip_weekends: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgencySocialTemplateORM(Base):
    __tablename__ = "agency_social_templates"
    __table_args__ = (
        PrimaryKeyConstraint("agency_id", "platform", name="pk_agency_social_templates"),
    )

    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    description_template: Mapped[str] = mapped_column(Text, nullable=False)
    title_template: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    hashtags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY[]::text[]")
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgencyMusicTrackORM(Base):
    __tablename__ = "agency_music_tracks"
    __table_args__ = (Index("idx_agency_music_tracks_agency", "agency_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "AgencyAutomationRulesORM",
    "AgencyBrandSettingsORM",
    "AgencyMusicTrackORM",
    "AgencyReelDefaultsORM",
    "AgencySocialTemplateORM",
    "RenderTemplateORM",
]
