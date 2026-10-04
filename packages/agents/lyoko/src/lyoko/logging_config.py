"""Logging configuration and access-log filtering for LYOKO."""

import logging

_HEALTH_PATHS = ("/health", "/healthz")


class HealthEndpointFilter(logging.Filter):
    """Filter out HTTP access log records for health check endpoints (/health, /healthz)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and len(record.args) >= 3:
            path = record.args[2]
            if isinstance(path, str):
                clean_path = path.split("?")[0].rstrip("/")
                if clean_path in _HEALTH_PATHS:
                    return False
        msg = record.getMessage()
        return not any(
            f"{method} {path}" in msg for method in ("GET", "HEAD") for path in _HEALTH_PATHS
        )


def configure_logging() -> None:
    """Configure root logging and silence health-check access log lines."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logging.getLogger("uvicorn.access").addFilter(HealthEndpointFilter())
