from __future__ import annotations

from urllib.parse import quote

from core.errors import SocialPublishingError
from services.social_delivery.gohighlevel_client import GoHighLevelClient
from services.social_delivery.models import (
    CreatedSocialPost,
    LocationUser,
    SocialAccount,
    UploadedMedia,
)


class GoHighLevelSocialService:
    def __init__(self, *, client: GoHighLevelClient) -> None:
        self.client = client

    def list_accounts(self, *, location_id: str, access_token: str) -> tuple[SocialAccount, ...]:
        payload = self.client.request_json(
            "GET",
            f"/social-media-posting/{quote(location_id, safe='')}/accounts",
            access_token=access_token,
        )
        results = payload.get("results", {})
        raw_accounts = results.get("accounts", []) if isinstance(results, dict) else []
        accounts: list[SocialAccount] = []
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            account_id = item.get("id")
            if not isinstance(account_id, str) or not account_id.strip():
                continue
            accounts.append(
                SocialAccount(
                    id=account_id.strip(),
                    name=str(item.get("name") or account_id).strip(),
                    platform=str(item.get("platform") or "").strip().lower(),
                    account_type=str(item.get("type") or "").strip(),
                    is_expired=bool(item.get("isExpired")),
                    raw_data=item,
                )
            )
        return tuple(accounts)

    def list_location_users(
        self,
        *,
        location_id: str,
        access_token: str,
    ) -> tuple[LocationUser, ...]:
        payload = self.client.request_json(
            "GET",
            "/users/",
            access_token=access_token,
            params={"locationId": location_id},
        )
        raw_users = payload.get("users", [])
        users: list[LocationUser] = []
        for item in raw_users:
            if not isinstance(item, dict):
                continue
            user_id = item.get("id")
            if not isinstance(user_id, str) or not user_id.strip():
                continue
            users.append(
                LocationUser(
                    id=user_id.strip(),
                    first_name=str(item.get("firstName") or "").strip(),
                    last_name=str(item.get("lastName") or "").strip(),
                    email=str(item.get("email") or "").strip(),
                    raw_data=item,
                )
            )
        return tuple(users)

    def create_reel_post(
        self,
        *,
        location_id: str,
        access_token: str,
        account_id: str,
        user_id: str,
        uploaded_media: UploadedMedia,
        platform: str,
        description: str,
        target_url: str | None = None,
    ) -> CreatedSocialPost:
        json_body: dict[str, object] = {
            "accountIds": [account_id],
            "summary": description,
            "media": [
                {
                    "url": uploaded_media.url,
                    "type": uploaded_media.mime_type,
                }
            ],
            "status": "published",
            "type": "reel",
            "userId": user_id,
        }
        json_body.update(
            self._build_platform_payload(
                platform=platform,
                target_url=target_url,
            )
        )
        payload = self.client.request_json(
            "POST",
            f"/social-media-posting/{quote(location_id, safe='')}/posts",
            access_token=access_token,
            json_body=json_body,
        )

        results = payload.get("results", {})
        if results is not None and not isinstance(results, dict):
            raise SocialPublishingError("GoHighLevel returned an unexpected post payload.")

        result_dict = results if isinstance(results, dict) else {}
        return CreatedSocialPost(
            post_id=self._extract_post_id(result_dict),
            status=self._extract_status(result_dict) or self._infer_status(payload),
            message=str(payload.get("message") or "").strip() or None,
            raw_response=payload,
        )

    @staticmethod
    def _extract_post_id(results: dict[str, object]) -> str | None:
        for key in ("id", "_id", "postId"):
            value = results.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_status(results: dict[str, object]) -> str | None:
        for key in ("status", "state"):
            value = results.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _infer_status(payload: dict[str, object]) -> str | None:
        top_level_status = payload.get("status")
        if isinstance(top_level_status, str) and top_level_status.strip():
            return top_level_status.strip()

        message = str(payload.get("message") or "").strip().lower()
        status_code = GoHighLevelSocialService._coerce_int(payload.get("statusCode"))
        success = payload.get("success")

        if message:
            if "published" in message:
                return "published"
            if "scheduled" in message:
                return "scheduled"
            if "queued" in message:
                return "queued"
            if "processing" in message:
                return "processing"
            if "created" in message:
                return "created"

        if success is True:
            if status_code == 202:
                return "accepted"
            if status_code in {200, 201}:
                return "created"

        return None

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _build_platform_payload(
        *,
        platform: str,
        target_url: str | None,
    ) -> dict[str, object]:
        del platform, target_url
        return {}


__all__ = ["GoHighLevelSocialService"]

