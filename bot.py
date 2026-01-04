import asyncio
import logging
import os

from telegram.ext import Application, ConversationHandler, CallbackQueryHandler, MessageHandler, CommandHandler, filters

from app.config import load_config
from app.db import init_db
from app.handlers.registration import get_handler as registration_handler
from app.handlers.courses import get_handlers as courses_handlers
from app.handlers.payment import get_handlers as payment_handlers
from app.handlers.admin import (
    get_handlers as admin_handlers,
    get_catchall_handler as admin_catchall_handler,
    AWAITING_DIRECT_MESSAGE,
    admin_msg_select_cb,
    capture_messages,
    cancel_cmd,
)


def setup_logging(debug: bool):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=level,
    )


def build_application(cfg, init_db_on_startup: bool = True):
    async def post_init(app: Application):
        if init_db_on_startup:
            await init_db(cfg.MONGODB_URL, cfg.MONGODB_DB_NAME)
        app.bot_data["ADMIN_ID"] = cfg.TELEGRAM_ADMIN_ID
        app.bot_data["SHAM"] = cfg.SHAM_CASH_NUMBER
        app.bot_data["HARAM"] = cfg.HARAM_NUMBER

    application = Application.builder().token(cfg.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Handlers - Order matters! More specific handlers first
    application.add_handler(registration_handler())

    # Direct admin -> student message conversation
    direct_message_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_msg_select_cb, pattern="^admin_msg_"),
        ],
        states={
            AWAITING_DIRECT_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, capture_messages),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        per_user=True,
        per_chat=False,
    )
    application.add_handler(direct_message_handler)

    # Admin handlers first
    for h in admin_handlers():
        application.add_handler(h)
    # Courses handlers
    for h in courses_handlers():
        application.add_handler(h)
    # Payment handlers
    for h in payment_handlers():
        application.add_handler(h)
    # Admin catch-all text handler LAST
    application.add_handler(admin_catchall_handler())

    return application


def main():
    cfg = load_config()
    setup_logging(cfg.DEBUG)

    if not cfg.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    app = build_application(cfg)

    if cfg.BOT_WEBHOOK_URL:
        public_url = cfg.BOT_WEBHOOK_URL.rstrip("/") + "/" + cfg.TELEGRAM_BOT_TOKEN
        app.run_webhook(
            listen=cfg.WEBAPP_HOST,
            port=cfg.WEBAPP_PORT,
            url_path=cfg.TELEGRAM_BOT_TOKEN,
            webhook_url=public_url,
            drop_pending_updates=True,
        )
    else:
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
