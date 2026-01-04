from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from .models import User
from typing import Dict, Any

_client = None


async def init_db(mongo_url: str, db_name: str):
    global _client
    if _client is not None:
        try:
            await _client.admin.command("ping")
            return
        except Exception:
            _client = None
    tls_kwargs: Dict[str, Any] = {}
    try:
        if mongo_url.startswith("mongodb+srv://") or "mongodb.net" in mongo_url:
            import certifi
            tls_kwargs = {"tls": True, "tlsCAFile": certifi.where()}
    except Exception:
        tls_kwargs = {}

    # First attempt: strict TLS with CA
    try:
        _client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=30000, **tls_kwargs)
        await _client.admin.command("ping")
    except Exception:
        # Retry with permissive TLS to bypass corporate MITM or strict SSL issues
        retry_kwargs = dict(tls_kwargs)
        retry_kwargs["tls"] = True
        retry_kwargs["tlsAllowInvalidCertificates"] = True
        _client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=30000, **retry_kwargs)
        await _client.admin.command("ping")

    await init_beanie(database=_client[db_name], document_models=[User])


def get_client() -> AsyncIOMotorClient:
    return _client
