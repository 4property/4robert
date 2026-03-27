from __future__ import annotations


class ApplicationError(RuntimeError):
    """Base class for application-level runtime failures."""


class ValidationError(ApplicationError):
    """Raised when runtime inputs are invalid."""


class ResourceNotFoundError(ApplicationError):
    """Raised when a required local resource cannot be found."""


class PhotoFilteringError(ApplicationError):
    """Raised when photo selection cannot complete."""


class PropertyReelError(ApplicationError):
    """Raised when reel generation cannot complete."""


class SocialPublishingError(ApplicationError):
    """Raised when external social publishing cannot complete."""


class TransientSocialPublishingError(SocialPublishingError):
    """Raised when external social publishing may succeed on retry."""


class DependencyNotInstalledError(ApplicationError):
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
        super().__init__(message)


__all__ = [
    "ApplicationError",
    "DependencyNotInstalledError",
    "PhotoFilteringError",
    "PropertyReelError",
    "ResourceNotFoundError",
    "SocialPublishingError",
    "TransientSocialPublishingError",
    "ValidationError",
]
