"""Application layer for the notifications bounded context.

Use cases live in :mod:`modules.notifications.application.use_cases`.
The dispatcher subscribes to ``outbox_events`` of type
``review_requested`` and produces ``email_send`` jobs that the worker
picks up via :class:`apps.worker.runtime.JobDispatcher`.
"""
