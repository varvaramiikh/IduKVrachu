import hmac
import hashlib
import urllib.parse
from .config import settings

def validate_init_data(init_data: str) -> bool:
    if settings.DEBUG:
        return True # Skip validation in debug mode
        
    vals = urllib.parse.parse_qs(init_data)
    if "hash" not in vals:
        return False
        
    hash_val = vals.pop("hash")[0]
    data_check_string = "\n".join([f"{k}={v[0]}" for k, v in sorted(vals.items())])
    
    secret_key = hmac.new(b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    return h == hash_val
