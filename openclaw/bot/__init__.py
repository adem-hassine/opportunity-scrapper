from __future__ import annotations

from telegram.ext import Application, CallbackQueryHandler

from openclaw.bot.handlers import handle_callback
from openclaw.core.config import Settings


def build_application(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app
