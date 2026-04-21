from __future__ import annotations

from urllib.parse import quote

from core.errors import SocialPublishingError
from services.publishing.social_delivery.gohighlevel_client import GoHighLevelClient
from services.publishing.social_delivery.models import (
    CreatedSocialPost,
    LocationUser,
    SocialAccount,
    UploadedMedia,
)
from services.publishing.social_delivery.platforms import get_platform_config


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

    def create_social_post(
        self,
        *,
        location_id: str,
        access_token: str,
        account_id: str,
        user_id: str,
        uploaded_media: UploadedMedia,
        platform: str,
        description: str,
        title: str | None = None,
        social_post_type: str,
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
            "type": social_post_type,
            "userId": user_id,
        }
        json_body.update(
            self._build_platform_payload(
                platform=platform,
                target_url=target_url,
                title=title,
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

    def get_social_post(
        self,
        *,
        location_id: str,
        access_token: str,
        post_id: str,
        platform: str | None = None,
        account_id: str | None = None,
    ) -> CreatedSocialPost:
        payload = self.client.request_json(
            "GET",
            f"/social-media-posting/{quote(location_id, safe='')}/posts/{quote(post_id, safe='')}",
            access_token=access_token,
        )
        result_dict = self._extract_post_payload(payload)
        verification_payload = self._extract_verification_payload(
            payload,
            platform=platform,
            account_id=account_id,
        )
        return CreatedSocialPost(
            post_id=self._extract_post_id(verification_payload) or self._extract_post_id(result_dict) or post_id,
            status=(
                self._extract_status(verification_payload)
                or self._extract_status(result_dict)
                or self._infer_status(payload)
            ),
            message=self._extract_message(payload, verification_payload, result_dict),
            raw_response=payload,
        )

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
        title: str | None = None,
        target_url: str | None = None,
    ) -> CreatedSocialPost:
        return self.create_social_post(
            location_id=location_id,
            access_token=access_token,
            account_id=account_id,
            user_id=user_id,
            uploaded_media=uploaded_media,
            platform=platform,
            description=description,
            title=title,
            social_post_type="reel",
            target_url=target_url,
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
        for key in ("status", "state", "postStatus", "publishStatus", "publishingStatus"):
            value = results.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_message(payload: dict[str, object], *containers: dict[str, object]) -> str | None:
        for container in (*containers, payload):
            for key in (
                "message",
                "error",
                "detail",
                "reason",
                "failedReason",
                "failureReason",
                "statusReason",
            ):
                value = container.get(key)
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
        title: str | None,
    ) -> dict[str, object]:
        platform_config = get_platform_config(platform)
        if platform_config is None:
            return {}
        return platform_config.build_gohighlevel_payload(target_url, title)

    @staticmethod
    def _extract_post_payload(payload: dict[str, object]) -> dict[str, object]:
        results = payload.get("results")
        if isinstance(results, dict):
            return results
        post = payload.get("post")
        if isinstance(post, dict):
            return post
        return payload

    @classmethod
    def _extract_verification_payload(
        cls,
        payload: dict[str, object],
        *,
        platform: str | None,
        account_id: str | None,
    ) -> dict[str, object]:
        candidates: list[tuple[int, dict[str, object]]] = []

        def visit(node: object) -> None:
            if isinstance(node, dict):
                candidate_status = cls._extract_status(node)
                if candidate_status is not None:
                    candidates.append((cls._score_status_candidate(node, platform=platform, account_id=account_id), node))
                for child in node.values():
                    visit(child)
                return
            if isinstance(node, list):
                for child in node:
                    visit(child)

        visit(payload)
        if not candidates:
            return cls._extract_post_payload(payload)

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @classmethod
    def _score_status_candidate(
        cls,
        candidate: dict[str, object],
        *,
        platform: str | None,
        account_id: str | None,
    ) -> int:
        score = 0
        normalized_platform = str(platform or "").strip().lower()
        normalized_account_id = str(account_id or "").strip()
        candidate_status = str(cls._extract_status(candidate) or "").strip().lower()

        candidate_platform = str(
            candidate.get("platform")
            or candidate.get("channel")
            or candidate.get("provider")
            or ""
        ).strip().lower()
        candidate_account_id = str(
            candidate.get("accountId")
            or candidate.get("socialAccountId")
            or candidate.get("channelId")
            or ""
        ).strip()

        if normalized_platform and candidate_platform == normalized_platform:
            score += 100
        if normalized_account_id and candidate_account_id == normalized_account_id:
            score += 100
        if normalized_account_id:
            raw_account_ids = candidate.get("accountIds")
            if isinstance(raw_account_ids, list) and normalized_account_id in {
                str(item).strip() for item in raw_account_ids
            }:
                score += 80
        if candidate_status in {"failed", "error", "rejected", "cancelled"}:
            score += 60
        if cls._extract_message(candidate, candidate) is not None:
            score += 10
        if candidate_platform or candidate_account_id:
            score += 5
        return score


__all__ = ["GoHighLevelSocialService"]
