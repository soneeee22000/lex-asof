"""Sentry and Datadog wiring.

Both are opt-in via environment variables and are no-ops when unset, so the service runs
locally and in CI with no accounts, no keys and no network. Observability that forces a
vendor dependency on every contributor is observability nobody runs.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def instrument(app: FastAPI) -> None:
    """Attach Sentry error reporting and Datadog tracing, if configured."""
    _instrument_sentry()
    _instrument_datadog(app)


def _instrument_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        logger.info("SENTRY_DSN unset; error reporting disabled")
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("APP_ENV", "local"),
        release=os.getenv("GIT_SHA", "unknown"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        # Legal questions are sensitive. Never ship request bodies to a third party.
        send_default_pii=False,
        integrations=[FastApiIntegration()],
    )
    logger.info("Sentry initialised")


def _instrument_datadog(app: FastAPI) -> None:
    if not os.getenv("DD_AGENT_HOST"):
        logger.info("DD_AGENT_HOST unset; tracing disabled")
        return

    from ddtrace import patch_all
    from ddtrace.contrib.asgi import TraceMiddleware

    patch_all()
    app.add_middleware(TraceMiddleware, integration_config={"service_name": "lex-asof"})
    logger.info("Datadog tracing initialised")
