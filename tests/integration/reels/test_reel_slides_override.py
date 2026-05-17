"""Integration tests for the PATCH ``.../reels/{site}/{property}/slides`` endpoint (feature 37).

Coverage:

* happy path: PATCH persists ``reels.manifest_override`` and re-enqueues
  a fresh ``reel_publish`` job, with ``render_status='pending'``.
* per-kind happy paths: ``photo`` / ``voiceover`` / ``text`` /
  ``intro_card`` / ``outro_card`` all accepted.
* clear semantics: ``slides=null`` AND ``slides=[]`` both wipe the
  override back to SQL ``NULL``.
* validation errors → **422** for:
    - invalid ``kind`` (``"banana"``);
    - missing per-kind required field (one test per kind);
    - position gap;
    - duplicate ``position``;
    - duplicate ``slide_id``;
    - sum of ``duration_seconds`` > target * 1.5;
    - extra field at slide level (``extra='forbid'``).
* 409 SLIDES_OVERRIDE_LOCKED:
    - ``workflow_state='approved'``;
    - ``publish_status='published'``.
* 404 for unknown reel.
* survives re-ingest: PATCH → trigger re-ingest → override stays set.

The renderer-side branch is exercised by
``tests/integration/rendering/test_render_with_slides_override.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    seed_property_with_reel,
)
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def _seed_reel_defaults(
    database_url: str,
    *,
    agency_id: str,
    duration_seconds: int = 30,
) -> None:
    timestamp = datetime.now(timezone.utc)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agency_reel_defaults ("
                    "agency_id, platforms, duration_seconds, music_id, "
                    "intro_enabled, caption_template, render_template_id, "
                    "settings, created_at, updated_at"
                    ") VALUES ("
                    ":agency_id, :platforms, :duration_seconds, '', TRUE, '', "
                    "'classic', CAST('{}' AS jsonb), :created_at, :updated_at"
                    ")"
                ),
                {
                    "agency_id": agency_id,
                    "platforms": ["instagram"],
                    "duration_seconds": duration_seconds,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()


def _read_manifest_override(
    database_url: str,
    *,
    external_source_id: str,
    source_property_id: int,
):
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT manifest_override FROM reels "
                    "WHERE external_source_id = :site "
                    "AND source_property_id = :pid"
                ),
                {
                    "site": external_source_id,
                    "pid": source_property_id,
                },
            ).first()
    finally:
        engine.dispose()
    return row.manifest_override if row is not None else None


def _slide(position: int, kind: str, **extra) -> dict:
    base = {
        "slide_id": f"slide-{position}-{kind}",
        "position": position,
        "duration_seconds": 3.0,
        "kind": kind,
    }
    base.update(extra)
    return base


_VALID_PHOTO = _slide(0, "photo", photo_position=0)
_VALID_VOICEOVER = _slide(1, "voiceover", audio_url="https://x.test/v.mp3")
_VALID_TEXT = _slide(2, "text", text="A short caption.")
_VALID_INTRO = _slide(3, "intro_card", title="Welcome", subtitle="Take a tour")
_VALID_OUTRO = _slide(
    4, "outro_card", title="Thanks", call_to_action="Book a viewing"
)
_VALID_ALL_KINDS = [
    _VALID_PHOTO,
    _VALID_VOICEOVER,
    _VALID_TEXT,
    _VALID_INTRO,
    _VALID_OUTRO,
]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_patch_slides_persists_override_and_flips_render_status() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(database.url, agency_id=seeded.agency_id)
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/slides",
                headers=ADMIN_BEARER,
                json={"slides": _VALID_ALL_KINDS},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["manifest_override"] == _VALID_ALL_KINDS
            assert body["render_status"] == "pending"
            assert body["publish_enqueued"] is True
            assert body["event_id"]
            assert body["job_id"]

            persisted = _read_manifest_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted == _VALID_ALL_KINDS

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.render_status == "pending"
            assert state.manifest_override == _VALID_ALL_KINDS


def test_patch_slides_with_null_clears_override() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            # Pre-seed an override so the clear has something to wipe.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET manifest_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": (
                                '[{"slide_id":"x","position":0,'
                                '"duration_seconds":3.0,"kind":"photo",'
                                '"photo_position":0}]'
                            ),
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    )
            finally:
                engine.dispose()

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/slides",
                headers=ADMIN_BEARER,
                json={"slides": None},
            )
            assert response.status_code == 200, response.text
            assert response.json()["manifest_override"] is None
            persisted = _read_manifest_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted is None


def test_patch_slides_with_empty_list_clears_override() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET manifest_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": (
                                '[{"slide_id":"x","position":0,'
                                '"duration_seconds":3.0,"kind":"photo",'
                                '"photo_position":0}]'
                            ),
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    )
            finally:
                engine.dispose()

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/slides",
                headers=ADMIN_BEARER,
                json={"slides": []},
            )
            assert response.status_code == 200, response.text
            assert response.json()["manifest_override"] is None
            persisted = _read_manifest_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted is None


# ---------------------------------------------------------------------------
# Validation errors (422)
# ---------------------------------------------------------------------------


def _run_invalid_payload_returns_422(payload: dict) -> int:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/slides",
                headers=ADMIN_BEARER,
                json=payload,
            )
            return response.status_code


def test_patch_slides_rejects_invalid_kind_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "slides": [
                _slide(0, "banana"),
            ]
        }
    ) == 422


def test_patch_slides_rejects_photo_missing_photo_position_with_422() -> None:
    payload_slide = {
        "slide_id": "p1",
        "position": 0,
        "duration_seconds": 3.0,
        "kind": "photo",
    }
    assert _run_invalid_payload_returns_422({"slides": [payload_slide]}) == 422


def test_patch_slides_rejects_voiceover_missing_audio_url_with_422() -> None:
    payload_slide = {
        "slide_id": "v1",
        "position": 0,
        "duration_seconds": 3.0,
        "kind": "voiceover",
    }
    assert _run_invalid_payload_returns_422({"slides": [payload_slide]}) == 422


def test_patch_slides_rejects_text_missing_text_with_422() -> None:
    payload_slide = {
        "slide_id": "t1",
        "position": 0,
        "duration_seconds": 3.0,
        "kind": "text",
    }
    assert _run_invalid_payload_returns_422({"slides": [payload_slide]}) == 422


def test_patch_slides_rejects_position_gap_with_422() -> None:
    # Two slides at positions 0 and 2 → gap at 1.
    assert _run_invalid_payload_returns_422(
        {
            "slides": [
                _slide(0, "photo", photo_position=0),
                _slide(2, "photo", photo_position=2),
            ]
        }
    ) == 422


def test_patch_slides_rejects_duplicate_position_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "slides": [
                _slide(0, "photo", photo_position=0),
                {
                    "slide_id": "dup-position",
                    "position": 0,
                    "duration_seconds": 3.0,
                    "kind": "photo",
                    "photo_position": 1,
                },
            ]
        }
    ) == 422


def test_patch_slides_rejects_duplicate_slide_id_with_422() -> None:
    duplicated_id = "duplicate-id"
    assert _run_invalid_payload_returns_422(
        {
            "slides": [
                {
                    "slide_id": duplicated_id,
                    "position": 0,
                    "duration_seconds": 3.0,
                    "kind": "photo",
                    "photo_position": 0,
                },
                {
                    "slide_id": duplicated_id,
                    "position": 1,
                    "duration_seconds": 3.0,
                    "kind": "photo",
                    "photo_position": 1,
                },
            ]
        }
    ) == 422


def test_patch_slides_rejects_duration_cap_exceeded_with_422() -> None:
    # Agency target is 30s; cap is 30 * 1.5 = 45s. Build 5 slides of 10s each
    # = 50s > 45s.
    slides = [
        _slide(position, "photo", photo_position=position, duration_seconds=10.0)
        for position in range(5)
    ]
    assert _run_invalid_payload_returns_422({"slides": slides}) == 422


def test_patch_slides_rejects_extra_field_at_slide_level_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "slides": [
                {
                    "slide_id": "extra-field",
                    "position": 0,
                    "duration_seconds": 3.0,
                    "kind": "photo",
                    "photo_position": 0,
                    "rogue_field": "bad",
                }
            ]
        }
    ) == 422


def test_patch_slides_rejects_extra_field_at_body_level_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "slides": [_VALID_PHOTO],
            "rogue_key": True,
        }
    ) == 422


# ---------------------------------------------------------------------------
# 409 — workflow / publish locked
# ---------------------------------------------------------------------------


def test_patch_slides_returns_409_when_workflow_state_is_approved() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                workflow_state="approved",
                publish_status="pending_publish",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/slides",
                headers=ADMIN_BEARER,
                json={"slides": _VALID_ALL_KINDS},
            )
            assert response.status_code == 409, response.text
            body = response.json()
            assert body["code"] == "SLIDES_OVERRIDE_LOCKED"
            assert body["details"]["context"]["workflow_state"] == "approved"


def test_patch_slides_returns_409_when_publish_status_is_published() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                workflow_state="published",
                publish_status="published",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/slides",
                headers=ADMIN_BEARER,
                json={"slides": None},
            )
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "SLIDES_OVERRIDE_LOCKED"


# ---------------------------------------------------------------------------
# 404 paths
# ---------------------------------------------------------------------------


def test_patch_slides_returns_404_for_unknown_reel() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/99/slides",
                headers=ADMIN_BEARER,
                json={"slides": None},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Survives re-ingest (point 5/6 of the 6-point pattern)
# ---------------------------------------------------------------------------


def test_slides_override_survives_re_ingest() -> None:
    """A re-save of the ReelState via the repository must preserve the
    persisted ``manifest_override`` value, even when the rebuilt state
    is constructed from ``_build_ingested_reel_state`` (the bug feature
    25 had for ``music_id`` and features 35 / 36 closed for their own
    columns).
    """
    from modules.reels.application.use_cases._ingest_property_assets import (
        _build_ingested_reel_state,
    )
    from modules.reels.domain.types import (
        MediaDeliveryPlan,
        PropertyMediaJob,
    )
    from modules.tenancy.domain.context import TenantContext
    from modules.catalog.domain.wordpress_property import Property

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/slides",
                headers=ADMIN_BEARER,
                json={"slides": _VALID_ALL_KINDS},
            )
            assert response.status_code == 200, response.text

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state_before = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state_before is not None
            assert state_before.manifest_override == _VALID_ALL_KINDS

            tenant = TenantContext(
                site_id=seeded.external_source_id,
                agency_id=seeded.agency_id,
                wordpress_source_id=seeded.ingestion_source_id,
            )
            property_item = Property.from_api_payload(
                {
                    "id": 42,
                    "slug": "sample",
                    "title": {"rendered": "Sample"},
                }
            )
            delivery_plan = MediaDeliveryPlan(
                listing_lifecycle="for_sale",
                artifact_kind="reel_video",
                render_profile="for_sale_reel",
                social_post_type="reel",
                asset_strategy="curated_selection",
                banner_text="FOR SALE",
            )
            job = PropertyMediaJob(
                event_id="evt-1",
                tenant=tenant,
                property_id=42,
                received_at=datetime.now(timezone.utc).isoformat(),
                raw_payload_hash="hash-1",
                payload={"id": 42},
            )
            rebuilt = _build_ingested_reel_state(
                job=job,
                property_item=property_item,
                state=state_before,
                delivery_plan=delivery_plan,
                content_fingerprint=state_before.content_fingerprint,
                content_snapshot=dict(state_before.content_snapshot),
                publish_target_fingerprint=state_before.publish_target_fingerprint,
                publish_target_snapshot=dict(state_before.publish_target_snapshot),
                requires_asset_preparation=True,
                requires_render=True,
                publish_context=None,
                pending_publish_platforms=(),
                reset_publish_history=False,
                normalized_external_source_id=seeded.external_source_id,
                render_template_id=state_before.render_template_id,
            )
            assert rebuilt.manifest_override == _VALID_ALL_KINDS

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                uow.reels.states.save(rebuilt)  # type: ignore[union-attr]
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state_after = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state_after is not None
            assert state_after.manifest_override == _VALID_ALL_KINDS
