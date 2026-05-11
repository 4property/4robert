"""Shared application errors. Implementation lives in `shared.errors.types`."""

from shared.errors.types import (
    ApplicationError,
    DependencyNotInstalledError,
    PhotoFilteringError,
    PipelineError,
    PropertyReelError,
    ResourceNotFoundError,
    SocialPublishingError,
    SocialPublishingResultError,
    TransientSocialPublishingError,
    TransientSocialPublishingResultError,
    ValidationError,
    extract_error_details,
)

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
