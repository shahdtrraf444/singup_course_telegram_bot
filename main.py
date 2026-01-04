import os
from contextlib import suppress

from fastapi import Request, Response
from telegram import Update

from windserve_app.main import app

from app.config import load_config
from bot import build_application, setup_logging

_tg_app = None


def _normalize_webhook_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.endswith("/"):
        url = url[:-1]
    if url.endswith("/bot"):
        return url
    return url + "/bot"


@app.post("/bot")
async def telegram_webhook(request: Request) -> Response:
    if _tg_app is None:
        return Response(status_code=503)
    payload = await request.json()
    update = Update.de_json(payload, _tg_app.bot)
    await _tg_app.update_queue.put(update)
    return Response(status_code=200)


@app.on_event("startup")
async def _startup() -> None:
    cfg = load_config()
    setup_logging(cfg.DEBUG)

    if not os.getenv("MONGODB_URL") or not os.getenv("MONGODB_DB_NAME"):
        raise RuntimeError("MONGODB_URL / MONGODB_DB_NAME are required")
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    if os.getenv("ENABLE_TELEGRAM_BOT", "true").lower() in {"0", "false", "no", "off"}:
        return

    webhook_url = _normalize_webhook_url(os.getenv("WEBHOOK_URL", ""))
    if not webhook_url:
        raise RuntimeError("WEBHOOK_URL is required (e.g. https://<repl-name>.<username>.repl.co)")

    print(f"Telegram webhook URL (set_webhook): {webhook_url}")

    global _tg_app
    _tg_app = build_application(cfg, init_db_on_startup=False)
    await _tg_app.initialize()
    await _tg_app.start()

    await _tg_app.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _tg_app
    if _tg_app is None:
        return
    with suppress(Exception):
        await _tg_app.stop()
    with suppress(Exception):
        await _tg_app.shutdown()
    _tg_app = None


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")
