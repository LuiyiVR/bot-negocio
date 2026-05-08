"""Envío de notificaciones a los socios autorizados."""
import asyncio
import logging

from config import ALLOWED_IDS

logger = logging.getLogger(__name__)


async def notificar_otros(bot, sender_id: int, text: str, **kwargs):
    """Envía a todos los socios autorizados excepto al remitente."""
    async def _send(uid):
        try:
            await bot.send_message(chat_id=uid, text=text, **kwargs)
        except Exception as e:
            logger.warning("No se pudo notificar a %s: %s", uid, e)

    tareas = [_send(uid) for uid in ALLOWED_IDS if uid != sender_id]
    if tareas:
        await asyncio.gather(*tareas)


async def notificar_a(bot, ids, text: str, **kwargs):
    """Envía a un conjunto específico de IDs."""
    async def _send(uid):
        try:
            await bot.send_message(chat_id=uid, text=text, **kwargs)
        except Exception as e:
            logger.warning("No se pudo notificar a %s: %s", uid, e)

    tareas = [_send(uid) for uid in ids if uid]
    if tareas:
        await asyncio.gather(*tareas)


async def notificar_otros_foto(bot, sender_id: int, photo: str, caption: str, **kwargs):
    """Envía una foto (file_id) con caption a todos los socios excepto el remitente."""
    async def _send(uid):
        try:
            await bot.send_photo(chat_id=uid, photo=photo, caption=caption, **kwargs)
        except Exception as e:
            logger.warning("No se pudo notificar foto a %s: %s", uid, e)

    tareas = [_send(uid) for uid in ALLOWED_IDS if uid != sender_id]
    if tareas:
        await asyncio.gather(*tareas)
