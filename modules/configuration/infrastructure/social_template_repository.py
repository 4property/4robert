from __future__ import annotations

from typing import Iterable, Mapping

from sqlalchemy import text

from modules.configuration.domain import SocialTemplate, SocialTemplateUpsert
from modules.configuration.infrastructure.repository_helpers import isoformat, list_param
from shared.db.repository_base import ModuleRepository, utcnow


class SocialTemplatesRepository(ModuleRepository):
    def list_for_agency(self, agency_id: str) -> tuple[SocialTemplate, ...]:
        rows = self.session.execute(
            text(
                "SELECT agency_id, platform, description_template, title_template, "
                "hashtags, created_at, updated_at FROM agency_social_templates "
                "WHERE agency_id = :agency_id ORDER BY platform ASC"
            ),
            {"agency_id": agency_id},
        ).all()
        return tuple(
            SocialTemplate(
                agency_id=str(row.agency_id),
                platform=str(row.platform),
                description_template=str(row.description_template or ""),
                title_template=str(row.title_template or ""),
                hashtags=tuple(row.hashtags or ()),
                created_at=isoformat(row.created_at) or "",
                updated_at=isoformat(row.updated_at) or "",
            )
            for row in rows
        )

    def get(self, *, agency_id: str, platform: str) -> SocialTemplate | None:
        row = self.session.execute(
            text(
                "SELECT agency_id, platform, description_template, title_template, "
                "hashtags, created_at, updated_at FROM agency_social_templates "
                "WHERE agency_id = :agency_id AND platform = :platform"
            ),
            {"agency_id": agency_id, "platform": platform},
        ).first()
        if row is None:
            return None
        return SocialTemplate(
            agency_id=str(row.agency_id),
            platform=str(row.platform),
            description_template=str(row.description_template or ""),
            title_template=str(row.title_template or ""),
            hashtags=tuple(row.hashtags or ()),
            created_at=isoformat(row.created_at) or "",
            updated_at=isoformat(row.updated_at) or "",
        )

    def upsert(
        self,
        *,
        agency_id: str,
        platform: str,
        description_template: str = "",
        title_template: str = "",
        hashtags: Iterable[str] | None = None,
    ) -> SocialTemplate:
        existing = self.get(agency_id=agency_id, platform=platform)
        timestamp = utcnow()
        self.session.execute(
            text(
                "INSERT INTO agency_social_templates ("
                "agency_id, platform, description_template, title_template, "
                "hashtags, created_at, updated_at"
                ") VALUES ("
                ":agency_id, :platform, :description_template, :title_template, "
                ":hashtags, :created_at, :updated_at"
                ") ON CONFLICT (agency_id, platform) DO UPDATE SET "
                "description_template = EXCLUDED.description_template, "
                "title_template = EXCLUDED.title_template, "
                "hashtags = EXCLUDED.hashtags, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "agency_id": agency_id,
                "platform": platform,
                "description_template": description_template,
                "title_template": title_template,
                "hashtags": list_param(hashtags),
                "created_at": existing.created_at if existing else timestamp,
                "updated_at": timestamp,
            },
        )
        result = self.get(agency_id=agency_id, platform=platform)
        assert result is not None
        return result

    def delete(self, *, agency_id: str, platform: str) -> bool:
        row = self.session.execute(
            text(
                "DELETE FROM agency_social_templates "
                "WHERE agency_id = :agency_id AND platform = :platform "
                "RETURNING platform"
            ),
            {"agency_id": agency_id, "platform": platform},
        ).first()
        return row is not None

    def delete_all_for_agency(self, *, agency_id: str) -> int:
        result = self.session.execute(
            text(
                "DELETE FROM agency_social_templates "
                "WHERE agency_id = :agency_id "
                "RETURNING platform"
            ),
            {"agency_id": agency_id},
        ).all()
        return len(result)

    def replace_all_for_agency(
        self,
        *,
        agency_id: str,
        templates: Mapping[str, SocialTemplateUpsert],
    ) -> tuple[SocialTemplate, ...]:
        """Bulk replace: drops every row for the agency and re-inserts the
        provided platforms with the rich per-platform payload.

        Each :class:`SocialTemplateUpsert` carries ``description_template``,
        ``title_template`` and ``hashtags``. The router converts the legacy
        string-only shape (``templates[platform] = "<description>"``) into
        ``SocialTemplateUpsert(description_template=...)`` before invoking
        the use case, so this method never sees a raw string. Empty values
        are persisted as empty strings / empty tuples (the columns default
        to those values in the schema).
        """
        self.delete_all_for_agency(agency_id=agency_id)
        for platform, upsert in templates.items():
            self.upsert(
                agency_id=agency_id,
                platform=platform,
                description_template=upsert.description_template,
                title_template=upsert.title_template,
                hashtags=upsert.hashtags,
            )
        return self.list_for_agency(agency_id)


__all__ = ["SocialTemplatesRepository"]
