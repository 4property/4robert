"""Notifications bounded context (feature 26 — infrastructure only).

Business logic that subscribes to outbox events and dispatches emails
arrives in feature 27. This module currently exposes:

* :mod:`modules.notifications.domain` — :class:`EmailRecord` + status
  constants.
* :mod:`modules.notifications.infrastructure` —
  :class:`EmailNotificationRepository`.
"""
