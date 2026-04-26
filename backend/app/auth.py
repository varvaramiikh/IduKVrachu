import logging
import hmac
import hashlib
import urllib.parse
from .config import settings

logger = logging.getLogger("backend.auth")


def validate_init_data(init_data: str) -> bool:
    if settings.DEBUG:
        logger.warning("auth: validate_init_data SKIPPED (DEBUG=True) — Telegram-подпись не проверяется")
        return True

    vals = urllib.parse.parse_qs(init_data)
    if "hash" not in vals:
        logger.warning("auth: initData отклонена — отсутствует поле 'hash'")
        return False

    hash_val = vals.pop("hash")[0]
    data_check_string = "\n".join([f"{k}={v[0]}" for k, v in sorted(vals.items())])

    secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if h == hash_val:
        logger.info("auth: HMAC initData OK")
        return True
    logger.warning("auth: HMAC initData mismatch — initData отклонена")
    return False
