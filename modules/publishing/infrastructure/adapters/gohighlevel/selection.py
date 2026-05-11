from __future__ import annotations

import logging

from modules.publishing.infrastructure.adapters.gohighlevel.normalization import (
    normalise_platform_name,
    selector_name,
)
from shared.errors import ResourceNotFoundError, ValidationError
from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    LocationUser,
    PlatformPublishTarget,
    PublishMediaRequest,
    SocialAccount,
)
from modules.publishing.infrastructure.adapters.gohighlevel.user_selection import (
    LocationUserFallbackSelector,
)
from modules.publishing.infrastructure.adapters.platforms import get_platform_config

logger = logging.getLogger(__name__)


class GoHighLevelSelectionMixin:
    fallback_user_selector: LocationUserFallbackSelector

    def _list_active_accounts(
        self,
        *,
        location_id: str,
        access_token: str,
    ) -> tuple[SocialAccount, ...]:
        return tuple(
            account
            for account in self.social_service.list_accounts(
                location_id=location_id,
                access_token=access_token,
            )
            if not account.is_expired
        )

    def _group_accounts_by_platform(
        self,
        accounts: tuple[SocialAccount, ...],
    ) -> dict[str, tuple[SocialAccount, ...]]:
        grouped_accounts: dict[str, list[SocialAccount]] = {}
        for account in accounts:
            normalized_platform = normalise_platform_name(account.platform)
            if not normalized_platform:
                continue
            grouped_accounts.setdefault(normalized_platform, []).append(account)
        return {
            platform: tuple(platform_accounts)
            for platform, platform_accounts in grouped_accounts.items()
        }

    @staticmethod
    def _resolve_account(
        *,
        eligible_accounts: tuple[SocialAccount, ...],
        requested_account_id: str | None,
        platform: str,
    ) -> SocialAccount:
        if not eligible_accounts:
            raise ResourceNotFoundError(
                f"No connected {platform} accounts were found for this "
                "GoHighLevel location.",
                context={"platform": platform},
                hint=(
                    "Connect the social account in GoHighLevel before retrying "
                    "the publish."
                ),
            )

        if requested_account_id:
            for account in eligible_accounts:
                if account.id == requested_account_id:
                    return account
            raise ValidationError(
                "Requested social account was not found for platform "
                f"{platform}: {requested_account_id}",
                context={
                    "platform": platform,
                    "requested_account_id": requested_account_id,
                },
                hint=(
                    "Refresh the configured account mapping and confirm the "
                    "account still exists in GoHighLevel."
                ),
            )

        selected_account = sorted(
            eligible_accounts,
            key=lambda account: (account.name.lower(), account.id),
        )[0]
        if len(eligible_accounts) > 1:
            logger.info(
                "Automatically selected the first available %s account: %s "
                "(%s available accounts).",
                platform,
                selected_account.id,
                len(eligible_accounts),
            )
        return selected_account

    def _resolve_user(
        self,
        *,
        location_users: tuple[LocationUser, ...],
        requested_user_id: str | None,
    ) -> LocationUser:
        if not location_users:
            raise ResourceNotFoundError(
                "No location users were found for this GoHighLevel location.",
                hint=(
                    "Add or sync at least one active user in the target "
                    "GoHighLevel location before publishing."
                ),
            )

        if requested_user_id:
            for user in location_users:
                if user.id == requested_user_id:
                    return user
            raise ValidationError(
                f"Requested GoHighLevel user was not found: {requested_user_id}",
                context={"requested_user_id": requested_user_id},
                hint=(
                    "Refresh the configured user mapping and confirm the user "
                    "still exists in GoHighLevel."
                ),
            )

        selected_user = self.fallback_user_selector(location_users)
        if len(location_users) > 1:
            selected_by = selector_name(self.fallback_user_selector)
            if selected_by == "select_first_available_location_user":
                logger.info(
                    "Automatically selected the first available GoHighLevel "
                    "user: %s (%s available users).",
                    selected_user.id,
                    len(location_users),
                )
            else:
                logger.info(
                    "Automatically selected a GoHighLevel user via %s: %s "
                    "(%s available users).",
                    selected_by,
                    selected_user.id,
                    len(location_users),
                )
        return selected_user

    @staticmethod
    def _resolve_batch_upload_file_name(
        request,
        desired_platforms: tuple[str, ...],
    ) -> str | None:
        if str(request.upload_file_name or "").strip():
            return request.upload_file_name
        for platform in desired_platforms:
            platform_config = get_platform_config(platform)
            if platform_config is None:
                continue
            upload_file_name = platform_config.build_upload_file_name(
                request.titles_by_platform.get(platform),
            )
            if upload_file_name:
                return upload_file_name
        return None

    @staticmethod
    def _resolve_upload_file_name_for_targets(
        targets: tuple[PlatformPublishTarget, ...],
    ) -> str | None:
        for target in targets:
            normalized_upload_file_name = str(target.upload_file_name or "").strip()
            if normalized_upload_file_name:
                return normalized_upload_file_name
        return None

    @staticmethod
    def _resolve_single_upload_file_name(request: PublishMediaRequest) -> str | None:
        if str(request.upload_file_name or "").strip():
            return request.upload_file_name
        platform_config = get_platform_config(request.platform)
        if platform_config is None:
            return None
        return platform_config.build_upload_file_name(request.title)


__all__ = ["GoHighLevelSelectionMixin"]
