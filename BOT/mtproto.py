"""Telethon (MTProto) layer — the things the Bot API cannot do.

The bot's transport is Bot API long-polling (ephemeral messages, Rich drafts,
forum topics all live there). Telethon is a *supplement* used only where MTProto
is strictly more capable:

  1. Premium custom emoji inside inline results. Bot API strips/rejects them in
     several inline contexts; MTProto renders them when the final content is
     applied with an explicit ``MessageEntityCustomEmoji`` via
     ``EditInlineBotMessageRequest``.
  2. Coloured inline-keyboard buttons (``KeyboardButtonStyle`` — primary/danger/
     success), which have no Bot API equivalent.
  3. Media in Rich messages by ``file_reference`` (``InputRichFilePhoto`` /
     ``InputRichFileDocument``) without re-uploading.

Requirements: ``TELEGRAM_API_ID`` + ``TELEGRAM_API_HASH`` in ``.env`` (collected
through the bot's ``/setup`` inline input) and the bot token. Absent creds -> the
layer stays disabled and the bot keeps working on Bot API alone.

Verified against Telethon 1.44.0 / TL layer 227:
  * ``SendMessageRequest(..., rich_message=InputRichMessageHTML(html=...))`` ✓
  * ``InputBotInlineMessageRichMessage(rich_message, reply_markup=)`` ✓
  * ``KeyboardButtonCallback(text, data, style=KeyboardButtonStyle(...))`` ✓
  * ephemeral messages: **absent** from layer 227 (Bot API 10.2 postdates the
    release) — that is why they stay on Bot API.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Iterable, List, Optional

log = logging.getLogger("lm_bot.telethon")

_AVAILABLE = True
try:
    from telethon import TelegramClient, events, functions
    from telethon.sessions import StringSession
    from telethon.tl import types as tl
except Exception:  # pragma: no cover - telethon missing
    _AVAILABLE = False
    TelegramClient = None  # type: ignore
    events = functions = tl = None  # type: ignore
    StringSession = None  # type: ignore


def utf16_offset(text: str, index: int) -> int:
    """UTF-16 code-unit offset of a Python string index.

    Telegram entity offsets are UTF-16 based; using Python code-point indices
    silently misplaces every entity after the first non-BMP character (emoji).
    """
    return len(text[:index].encode("utf-16-le")) // 2


def utf16_len(fragment: str) -> int:
    return len(fragment.encode("utf-16-le")) // 2


def emoji_entities(text: str, mapping: Iterable[tuple]) -> List:
    """Build MessageEntityCustomEmoji list from (placeholder, document_id) pairs.

    Each placeholder must appear literally in ``text``; offsets are computed in
    UTF-16 units as Telegram requires.
    """
    if not _AVAILABLE:
        return []
    out = []
    for glyph, doc_id in mapping:
        start = 0
        while True:
            idx = text.find(glyph, start)
            if idx < 0:
                break
            out.append(tl.MessageEntityCustomEmoji(
                offset=utf16_offset(text, idx),
                length=utf16_len(glyph),
                document_id=int(doc_id),
            ))
            start = idx + len(glyph)
    return out


def styled_button(text: str, data: str, style: str = "primary"):
    """Callback button with a colour. Bot API has no equivalent for this."""
    if not _AVAILABLE:
        return None
    kw = {}
    if style == "primary":
        kw["bg_primary"] = True
    elif style == "danger":
        kw["bg_danger"] = True
    elif style == "success":
        kw["bg_success"] = True
    return tl.KeyboardButtonCallback(
        text=text,
        data=data.encode() if isinstance(data, str) else data,
        style=tl.KeyboardButtonStyle(**kw) if kw else None,
    )


def inline_input_button(text: str, query: str, style: str = "primary"):
    """switch_inline_query_current_chat button (Heroku form.py input pattern)."""
    if not _AVAILABLE:
        return None
    kw = {"bg_primary": True} if style == "primary" else (
        {"bg_danger": True} if style == "danger" else {"bg_success": True})
    return tl.KeyboardButtonSwitchInline(
        text=text, query=query, same_peer=True,
        style=tl.KeyboardButtonStyle(**kw),
    )


def markup(rows: List[List]):
    if not _AVAILABLE:
        return None
    return tl.ReplyInlineMarkup(rows=[
        tl.KeyboardButtonRow(buttons=[b for b in row if b is not None])
        for row in rows if row
    ])


class TelethonLayer:
    """Optional MTProto side-car for the Bot API bot."""

    def __init__(self, api_id: Optional[int], api_hash: str, bot_token: str,
                 session_dir: str = "/tmp"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.session_path = os.path.join(session_dir, "lmarena_bot_mtproto")
        self.client = None
        self._lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return bool(_AVAILABLE and self.api_id and self.api_hash and self.bot_token)

    def why_unavailable(self) -> str:
        if not _AVAILABLE:
            return "telethon is not installed"
        if not self.bot_token:
            return "BOT_TOKEN missing"
        if not self.api_id or not self.api_hash:
            return "TELEGRAM_API_ID / TELEGRAM_API_HASH missing (run /setup in the bot)"
        return ""

    async def start(self) -> bool:
        """Connect as a bot. Safe to call repeatedly."""
        if not self.available:
            log.info("telethon layer disabled: %s", self.why_unavailable())
            return False
        async with self._lock:
            if self.client is not None and self.client.is_connected():
                return True
            try:
                self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)
                await self.client.start(bot_token=self.bot_token)
                me = await self.client.get_me()
                log.info("telethon layer up as @%s", getattr(me, "username", "?"))
                return True
            except Exception as e:
                log.warning("telethon layer failed to start: %s", e)
                self.client = None
                return False

    async def stop(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    # ── capabilities ─────────────────────────────────────────────────────────
    async def send_rich(self, peer, html: str, buttons=None):
        """Rich message through MTProto (accepts InputRichMessageHTML)."""
        if not await self.start():
            return None
        import random
        return await self.client(functions.messages.SendMessageRequest(
            peer=await self.client.get_input_entity(peer),
            message="",
            random_id=random.getrandbits(63),
            rich_message=tl.InputRichMessageHTML(html=html),
            reply_markup=buttons,
        ))

    async def edit_inline_with_emoji(self, inline_msg_id, text: str, mapping):
        """Final inline edit carrying real premium custom emoji entities.

        The pre-edit + short sleep is required: Telegram locks inline content on
        first render, and only a subsequent MTProto edit renders custom emoji.
        """
        if not await self.start():
            return None
        await self.client(functions.messages.EditInlineBotMessageRequest(
            id=inline_msg_id, message="⏳", reply_markup=None))
        await asyncio.sleep(0.3)
        return await self.client(functions.messages.EditInlineBotMessageRequest(
            id=inline_msg_id, message=text,
            entities=emoji_entities(text, mapping)))

    async def edit_inline_rich(self, inline_msg_id, html: str, buttons=None, files=None):
        """Rich (HTML) inline edit, optionally with pre-uploaded media refs."""
        if not await self.start():
            return None
        return await self.client(functions.messages.EditInlineBotMessageRequest(
            id=inline_msg_id,
            rich_message=tl.InputRichMessageHTML(html=html, files=files or None),
            reply_markup=buttons,
        ))

    async def create_forum_topic(self, peer, title: str, icon_color: int = 0x6FB9F0):
        """messages.CreateForumTopic — works when Bot API rights are awkward."""
        if not await self.start():
            return None
        import uuid
        return await self.client(functions.messages.CreateForumTopicRequest(
            peer=await self.client.get_input_entity(peer),
            title=title,
            icon_color=icon_color,
            random_id=uuid.uuid4().int & 0x7FFFFFFF,
        ))


def build_layer(secrets_module) -> TelethonLayer:
    """Construct the layer from .env-held credentials."""
    return TelethonLayer(
        api_id=secrets_module.telegram_api_id(),
        api_hash=secrets_module.telegram_api_hash(),
        bot_token=secrets_module.bot_token(),
    )
