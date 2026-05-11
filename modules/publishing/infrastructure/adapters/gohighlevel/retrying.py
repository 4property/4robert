from __future__ import annotations

import logging
import time

from shared.errors import TransientSocialPublishingError
from shared.observability import format_console_block, format_detail_line
from modules.publishing.infrastructure.adapters.gohighlevel.client import GoHighLevelApiError

logger = logging.getLogger(__name__)


class GoHighLevelRetryMixin:
    retry_attempts: int
    retry_backoff_seconds: float

    def _run_with_retry(
        self,
        operation,
        *,
        location_id: str,
        operation_name: str,
        platform_label: str,
    ):
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return operation()
            except (TransientSocialPublishingError, GoHighLevelApiError) as error:
                last_error = error
                if not self._should_retry(error=error, attempt=attempt):
                    raise
                logger.warning(
                    format_console_block(
                        "GoHighLevel Publish Retry",
                        format_detail_line("Attempt", f"{attempt}/{self.retry_attempts}"),
                        format_detail_line("Location ID", location_id),
                        format_detail_line("Platform", platform_label),
                        format_detail_line("Operation", operation_name),
                        format_detail_line("Reason", error),
                    )
                )
                time.sleep(self.retry_backoff_seconds * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{operation_name} failed without an error.")

    def _should_retry(self, *, error: Exception, attempt: int) -> bool:
        if attempt >= self.retry_attempts:
            return False
        if isinstance(error, TransientSocialPublishingError):
            return True
        if isinstance(error, GoHighLevelApiError):
            return error.status_code >= 500
        return False

    def _is_retryable_error(self, error: Exception) -> bool:
        if isinstance(error, TransientSocialPublishingError):
            return True
        if isinstance(error, GoHighLevelApiError):
            return error.status_code >= 500
        return False


__all__ = ["GoHighLevelRetryMixin"]
