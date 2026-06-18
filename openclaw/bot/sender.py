from __future__ import annotations

import asyncio

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from openclaw.core.config import Settings
from openclaw.models.storage import OpportunityRecord
from openclaw.workflows.qualification import QualificationPacket


async def _send(
    settings: Settings,
    record: OpportunityRecord,
    packet: QualificationPacket,
) -> None:
    keyboard = [[
        InlineKeyboardButton(btn.label, callback_data=btn.callback_data)
        for btn in packet.telegram_buttons
    ]]
    markup = InlineKeyboardMarkup(keyboard)
    async with Bot(token=settings.telegram_bot_token) as bot:
        await bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=packet.telegram_message,
            reply_markup=markup,
        )


def send_alert_for_opportunity(
    settings: Settings,
    record: OpportunityRecord,
    packet: QualificationPacket,
) -> None:
    """Send a Telegram alert for a single opportunity. Caller must ensure route == ALERT."""
    asyncio.run(_send(settings, record, packet))
