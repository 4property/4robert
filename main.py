from __future__ import annotations

import argparse
import logging
from pathlib import Path

from application.bootstrap import build_default_job_dispatcher
from core.errors import ApplicationError
from core.logging import configure_logging, format_console_block, format_detail_line
from config import LOG_LEVEL, WEBHOOK_HOST, WEBHOOK_PORT
from services.webhook_transport.server import run_wordpress_webhook_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the WordPress webhook server.")
    parser.add_argument("--host", default=WEBHOOK_HOST)
    parser.add_argument("--port", type=int, default=WEBHOOK_PORT)
    args = parser.parse_args()

    configure_logging(LOG_LEVEL)
    base_dir = Path(__file__).resolve().parent
    dispatcher = build_default_job_dispatcher(base_dir)
    logger = logging.getLogger(__name__)

    try:
        run_wordpress_webhook_server(
            base_dir,
            dispatcher=dispatcher,
            host=args.host,
            port=args.port,
        )
    except ApplicationError as error:
        logger.error(
            format_console_block(
                "Application Startup Failed",
                format_detail_line("Reason", error),
            )
        )
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        logger.info(
            format_console_block(
                "Server Stopped",
                "The webhook server shut down after receiving an interrupt.",
            )
        )


if __name__ == "__main__":
    main()

