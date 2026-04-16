import logging
import os
import re
from typing import Any

SECRET_NAME_PATTERNS = ("TOKEN", "SECRET", "KEY", "PASSWORD", "PASS", "PWD")
_DB_URL_CREDENTIALS_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(p in upper for p in SECRET_NAME_PATTERNS)


def mask_value(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def mask_url_credentials(url: str) -> str:
    return _DB_URL_CREDENTIALS_RE.sub(lambda m: m.group(1) + "***" + m.group(3), url)


def format_value(name: str, value: Any) -> str:
    if value is None:
        return "<unset>"
    text = str(value)
    if _is_secret_name(name):
        return mask_value(text)
    if "://" in text:
        return mask_url_credentials(text)
    return text


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def log_environment(logger: logging.Logger, header: str = "Environment variables") -> None:
    logger.info("--- %s ---", header)
    for key in sorted(os.environ.keys()):
        logger.info("  %s=%s", key, format_value(key, os.environ[key]))
    logger.info("--- end environment ---")


def log_settings(logger: logging.Logger, settings_obj: Any, header: str = "App settings") -> None:
    logger.info("--- %s ---", header)
    data = settings_obj.model_dump() if hasattr(settings_obj, "model_dump") else dict(settings_obj)
    for key in sorted(data.keys()):
        logger.info("  %s=%s", key, format_value(key, data[key]))
    logger.info("--- end settings ---")
