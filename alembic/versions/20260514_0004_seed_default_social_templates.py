"""Backfill default ``agency_social_templates`` rows for existing agencies.

New agencies receive these defaults via
``modules.tenancy.application.use_cases.register_agency.RegisterAgencyUseCase``,
which calls ``build_default_social_templates()`` after persisting the
``agencies`` row. This migration handles agencies that already exist:
for every ``(agency_id, platform)`` pair in the canonical default set
that does NOT have a row yet, insert one with the default body, title
(=address) and empty hashtags.

Existing rows are left untouched so agency customizations applied via
``PUT /v1/admin/agencies/{id}/social-templates`` are NEVER overwritten.

The literal template strings here MUST stay in sync with
``modules/configuration/domain/default_social_templates.py``. The Python
module is the canonical source for runtime; this SQL mirrors it for
one-shot backfill. If the templates evolve in the future, the new
migration ships the new defaults and existing rows (default or customized)
are left as-is.

``downgrade()`` deletes only rows whose content matches the defaults this
migration inserted, again leaving customized rows intact.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260514_0004"
down_revision = "20260514_0003"
branch_labels = None
depends_on = None


_TITLE = "{{property_title}}"

_BODY_GENERIC = (
    "\U0001F4CD {{property_title}}\n"
    "\U0001F4B6 {{price}}\n"
    "\U0001F6CF {{bedrooms}} Beds | \U0001F6C1 {{bathrooms}} Baths\n"
    "\U0001F4D0 {{size_m2}} sq.m\n"
    "\n"
    "{{short_description}}\n"
    "\n"
    "{{agent_name}} · {{agent_phone}}\n"
    "{{property_url}}"
)

_BODY_GBP = (
    "{{price}} · {{bedrooms}} bed · {{size_m2}} sq.m\n"
    "{{property_title}}\n"
    "\n"
    "{{short_description}}\n"
    "\n"
    "{{agent_name}} · {{agent_email}}\n"
    "{{property_url}}"
)

_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("instagram", _BODY_GENERIC),
    ("tiktok", _BODY_GENERIC),
    ("facebook", _BODY_GENERIC),
    ("linkedin", _BODY_GENERIC),
    ("youtube", _BODY_GENERIC),
    ("pinterest", _BODY_GENERIC),
    ("gbp", _BODY_GBP),
)


def upgrade() -> None:
    conn = op.get_bind()
    # For each canonical (platform, body) default, insert a row for every
    # agency that does not yet have ONE for that platform. Empty hashtags
    # (``ARRAY[]::text[]``) and the title template are constant across all
    # rows. ``NOT EXISTS`` keeps the migration idempotent and never
    # overwrites a customized row.
    for platform, body in _DEFAULTS:
        conn.execute(
            sa.text(
                "INSERT INTO agency_social_templates ("
                "    agency_id, platform, description_template, title_template, "
                "    hashtags, created_at, updated_at"
                ") "
                "SELECT a.id, :platform, :body, :title, ARRAY[]::text[], NOW(), NOW() "
                "FROM agencies a "
                "WHERE NOT EXISTS ("
                "    SELECT 1 FROM agency_social_templates t "
                "    WHERE t.agency_id = a.id AND t.platform = :platform"
                ")"
            ),
            {"platform": platform, "body": body, "title": _TITLE},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # Delete only rows that still match the defaults this migration inserted.
    # Rows the agency customized via PUT /social-templates have a different
    # description_template, title_template or hashtags array and survive.
    for platform, body in _DEFAULTS:
        conn.execute(
            sa.text(
                "DELETE FROM agency_social_templates "
                "WHERE platform = :platform "
                "  AND description_template = :body "
                "  AND title_template = :title "
                "  AND COALESCE(array_length(hashtags, 1), 0) = 0"
            ),
            {"platform": platform, "body": body, "title": _TITLE},
        )
