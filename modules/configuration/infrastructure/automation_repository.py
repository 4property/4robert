from __future__ import annotations

from typing import Iterable

from sqlalchemy import text

from modules.configuration.domain import AutomationRules
from modules.configuration.infrastructure.repository_helpers import isoformat, list_param
from shared.db.repository_base import ModuleRepository, utcnow


class AutomationRulesRepository(ModuleRepository):
    def get(self, agency_id: str) -> AutomationRules | None:
        row = self.session.execute(
            text(
                "SELECT agency_id, approval_required, publish_window_start, "
                "publish_window_end, publish_days, trigger_on_status, created_at, "
                "updated_at FROM agency_automation_rules WHERE agency_id = :agency_id"
            ),
            {"agency_id": agency_id},
        ).first()
        if row is None:
            return None
        return AutomationRules(
            agency_id=str(row.agency_id),
            approval_required=bool(row.approval_required),
            publish_window_start=str(row.publish_window_start or ""),
            publish_window_end=str(row.publish_window_end or ""),
            publish_days=tuple(row.publish_days or ()),
            trigger_on_status=tuple(row.trigger_on_status or ()),
            created_at=isoformat(row.created_at) or "",
            updated_at=isoformat(row.updated_at) or "",
        )

    def upsert(
        self,
        *,
        agency_id: str,
        approval_required: bool | None = None,
        publish_window_start: str | None = None,
        publish_window_end: str | None = None,
        publish_days: Iterable[str] | None = None,
        trigger_on_status: Iterable[str] | None = None,
    ) -> AutomationRules:
        existing = self.get(agency_id)
        timestamp = utcnow()
        merged = {
            "approval_required": bool(
                approval_required
                if approval_required is not None
                else (existing.approval_required if existing else False)
            ),
            "publish_window_start": publish_window_start
            if publish_window_start is not None
            else (existing.publish_window_start if existing else "00:00"),
            "publish_window_end": publish_window_end
            if publish_window_end is not None
            else (existing.publish_window_end if existing else "23:59"),
            "publish_days": (
                list_param(publish_days)
                if publish_days is not None
                else (
                    list(existing.publish_days)
                    if existing
                    else ["mon", "tue", "wed", "thu", "fri"]
                )
            ),
            "trigger_on_status": (
                list_param(trigger_on_status)
                if trigger_on_status is not None
                else (
                    list(existing.trigger_on_status)
                    if existing
                    else ["for_sale", "to_let"]
                )
            ),
        }
        self.session.execute(
            text(
                "INSERT INTO agency_automation_rules ("
                "agency_id, approval_required, publish_window_start, "
                "publish_window_end, publish_days, trigger_on_status, "
                "created_at, updated_at"
                ") VALUES ("
                ":agency_id, :approval_required, :publish_window_start, "
                ":publish_window_end, :publish_days, :trigger_on_status, "
                ":created_at, :updated_at"
                ") ON CONFLICT (agency_id) DO UPDATE SET "
                "approval_required = EXCLUDED.approval_required, "
                "publish_window_start = EXCLUDED.publish_window_start, "
                "publish_window_end = EXCLUDED.publish_window_end, "
                "publish_days = EXCLUDED.publish_days, "
                "trigger_on_status = EXCLUDED.trigger_on_status, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "agency_id": agency_id,
                **merged,
                "created_at": existing.created_at if existing else timestamp,
                "updated_at": timestamp,
            },
        )
        result = self.get(agency_id)
        assert result is not None
        return result


__all__ = ["AutomationRulesRepository"]
