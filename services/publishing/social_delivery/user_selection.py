from __future__ import annotations

import random
from collections.abc import Callable

from services.publishing.social_delivery.models import LocationUser

LocationUserFallbackSelector = Callable[[tuple[LocationUser, ...]], LocationUser]


def select_first_available_location_user(location_users: tuple[LocationUser, ...]) -> LocationUser:
    return sorted(
        location_users,
        key=lambda user: (user.display_name.lower(), user.id),
    )[0]


def select_random_location_user(location_users: tuple[LocationUser, ...]) -> LocationUser:
    return random.SystemRandom().choice(location_users)


__all__ = [
    "LocationUserFallbackSelector",
    "select_first_available_location_user",
    "select_random_location_user",
]

