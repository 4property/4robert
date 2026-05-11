from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _normalise_error_context(context: Mapping[str, object] | None) -> dict[str, object]:
    if not context:
        return {}
    normalized: dict[str, object] = {}
    for key, value in context.items():
        normalized_key = str(key).strip()
        if not normalized_key or value in (None, "", (), [], {}):
            continue
        normalized[normalized_key] = value
    return normalized


class ApplicationError(RuntimeError):
    """Base class for application-level runtime failures."""

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        cause: object | None = None,
    ) -> None:
        self.context = _normalise_error_context(context)
        self.hint = str(hint).strip() if hint not in (None, "") else None
        self.cause = cause
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "message": str(self),
            "type": self.__class__.__name__,
        }
        if self.context:
            payload["context"] = dict(self.context)
        if self.hint:
            payload["hint"] = self.hint
        if self.cause not in (None, ""):
            payload["cause"] = str(self.cause)
        return payload


class PipelineError(ApplicationError):
    """Runtime failure with structured pipeline metadata."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "runtime",
        code: str = "PIPELINE_ERROR",
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        self.stage = stage
        self.code = code
        self.retryable = retryable
        self.context = _normalise_error_context(context)
        self.external_trace_id = (
            str(external_trace_id).strip() if external_trace_id not in (None, "") else None
        )
        super().__init__(
            message,
            context=context,
            hint=hint,
            cause=cause,
        )

    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        payload.update(
            {
            "stage": self.stage,
            "code": self.code,
            "retryable": self.retryable,
            }
        )
        if self.external_trace_id:
            payload["external_trace_id"] = self.external_trace_id
        return payload


class ValidationError(PipelineError):
    """Raised when runtime inputs are invalid."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "validation",
        code: str = "VALIDATION_ERROR",
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class ResourceNotFoundError(PipelineError):
    """Raised when a required local resource cannot be found."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "resource_lookup",
        code: str = "RESOURCE_NOT_FOUND",
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class PhotoFilteringError(PipelineError):
    """Raised when photo selection cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "asset_preparation",
        code: str = "PHOTO_FILTERING_ERROR",
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class PropertyReelError(PipelineError):
    """Raised when reel generation cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "render",
        code: str = "PROPERTY_REEL_ERROR",
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class SocialPublishingError(PipelineError):
    """Raised when external social publishing cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "publish",
        code: str = "SOCIAL_PUBLISHING_ERROR",
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class SocialPublishingResultError(SocialPublishingError):
    """Raised when social publishing fails after producing structured outcome details."""

    def __init__(
        self,
        message: str,
        *,
        result: object | None = None,
        stage: str = "publish",
        code: str = "SOCIAL_PUBLISHING_RESULT_ERROR",
        retryable: bool = False,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        self.result = result
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class TransientSocialPublishingError(SocialPublishingError):
    """Raised when external social publishing may succeed on retry."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "publish",
        code: str = "TRANSIENT_SOCIAL_PUBLISHING_ERROR",
        retryable: bool = True,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class TransientSocialPublishingResultError(TransientSocialPublishingError):
    """Raised when retryable social publishing fails after producing structured outcome details."""

    def __init__(
        self,
        message: str,
        *,
        result: object | None = None,
        stage: str = "publish",
        code: str = "TRANSIENT_SOCIAL_PUBLISHING_RESULT_ERROR",
        retryable: bool = True,
        context: Mapping[str, object] | None = None,
        hint: str | None = None,
        external_trace_id: str | None = None,
        cause: object | None = None,
    ) -> None:
        self.result = result
        super().__init__(
            message,
            stage=stage,
            code=code,
            retryable=retryable,
            context=context,
            hint=hint,
            external_trace_id=external_trace_id,
            cause=cause,
        )


class DependencyNotInstalledError(PipelineError):
    """Raised when an optional third-party dependency is missing."""

    def __init__(
        self,
        *,
        module_name: str,
        package_name: str | None = None,
        display_name: str | None = None,
        feature: str | None = None,
    ) -> None:
        self.module_name = module_name
        self.package_name = package_name or module_name
        self.display_name = display_name or self.package_name
        self.feature = feature

        message = f"{self.display_name} is not installed."
        if feature:
            message = f"{self.display_name} is required for {feature} but is not installed."
        message += f" Install it with: pip install {self.package_name}"
        super().__init__(
            message,
            stage="dependency",
            code="DEPENDENCY_NOT_INSTALLED",
            retryable=False,
            context={"module_name": self.module_name, "feature": self.feature or ""},
            hint="Activate the project virtual environment and reinstall the runtime dependencies.",
        )


def extract_error_details(error: object) -> dict[str, Any]:
    if isinstance(error, ApplicationError):
        return error.to_dict()
    return {
        "message": str(error),
        "type": error.__class__.__name__,
    }


__all__ = [
    "ApplicationError",
    "DependencyNotInstalledError",
    "PhotoFilteringError",
    "PipelineError",
    "PropertyReelError",
    "ResourceNotFoundError",
    "SocialPublishingError",
    "SocialPublishingResultError",
    "TransientSocialPublishingError",
    "TransientSocialPublishingResultError",
    "ValidationError",
    "extract_error_details",
]
