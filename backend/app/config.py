import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str
    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"
    SECRET_KEY: str = "dev_secret_key"
    DEBUG: bool = True
    WEB_APP_URL: str = "http://localhost:8000"
    
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
