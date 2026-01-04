import os
from dataclasses import dataclass


def str_to_bool(v: str) -> bool:
    return str(v).lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Config:
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ADMIN_ID: int
    MONGODB_URL: str
    MONGODB_DB_NAME: str
    SHAM_CASH_NUMBER: str
    HARAM_NUMBER: str
    DEBUG: bool
    BOT_WEBHOOK_URL: str
    WEBAPP_HOST: str
    WEBAPP_PORT: int


def load_config() -> Config:
    port_str = os.getenv("PORT") or os.getenv("WEBAPP_PORT") or "8080"
    return Config(
        TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        TELEGRAM_ADMIN_ID=int(os.getenv("TELEGRAM_ADMIN_ID", "0")),
        MONGODB_URL=os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
        MONGODB_DB_NAME=os.getenv("MONGODB_DB_NAME", "telegram_courses"),
        SHAM_CASH_NUMBER=os.getenv("SHAM_CASH_NUMBER", ""),
        HARAM_NUMBER=os.getenv("HARAM_NUMBER", ""),
        DEBUG=str_to_bool(os.getenv("DEBUG", "true")),
        BOT_WEBHOOK_URL=os.getenv("BOT_WEBHOOK_URL", ""),
        WEBAPP_HOST=os.getenv("WEBAPP_HOST", "0.0.0.0"),
        WEBAPP_PORT=int(port_str),
    )
