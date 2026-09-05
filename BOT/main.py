#!/usr/bin/env python3
"""
Onboarding-бот в стиле Heroku form.py (Rich Messages, Bot API 10.3).

Собирает api_id / api_hash у владельца через inline-форму с кнопками:
  → Далее · ↑ Назад · ↓ Готово · ← Отмена
Вся навигация — callback-кнопки внутри rich_message; состояние шага живёт
в объекте OnboardingForm (как unit form в form.py).

Режимы (совместимо с Setuper.sh):
  python3 BOT/main.py --mode echo       --token <BOT_TOKEN>
  python3 BOT/main.py --mode forward    --token <BOT_TOKEN> --owner <OWNER_ID>
  python3 BOT/main.py --mode onboarding --token <BOT_TOKEN> --owner <OWNER_ID> --output <CREDS_FILE>

Только aiohttp + Bot API (без Telethon).
"""
import argparse
import asyncio
import html
import json
import os
import sys
import time
import traceback
from pathlib import Path

import aiohttp

API_URL = "https://api.telegram.org/bot"

# ── Premium emoji (tg-emoji) — только в капшонах, не в кнопках ──────────────
EMOJI = {
    "cool": '<tg-emoji emoji-id="5449619723966761441">😌</tg-emoji>',
    "ok": '<tg-emoji emoji-id="5447363161034346459">👌</tg-emoji>',
    "brain": '<tg-emoji emoji-id="5447595110743168717">🧠</tg-emoji>',
}

# Стрелки навигации (вместо любых эмодзи в кнопках)
A_NEXT = "→ Далее"
A_BACK = "↑ Назад"
A_DONE = "↓ Готово"
A_CANCEL = "← Отмена"

FORM_TTL = 300  # секунд, как ttl в form.py


class APIClient:
    """Тонкая обёртка над Bot API: aiohttp, ретраи, 429."""

    def __init__(self, token: str, session: aiohttp.ClientSession):
        self.base = f"{API_URL}{token}"
        self.session = session

    async def request(self, method: str, payload: dict | None = None, retries: int = 3):
        url = f"{self.base}/{method}"
        for _ in range(retries):
            try:
                async with self.session.post(url, json=payload or {}) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        if data.get("error_code") == 429:
                            ra = data.get("parameters", {}).get("retry_after", 1)
                            await asyncio.sleep(ra + 0.1)
                            continue
                        print(f"API Error ({method}):", str(data)[:200])
                    return data.get("result")
            except Exception as e:
                print(f"Request Exception ({method}):", e)
                await asyncio.sleep(1)
        return None

    async def get_updates(self, offset=None):
        params = {"timeout": 30}
        if offset:
            params["offset"] = offset
        try:
            async with self.session.get(f"{self.base}/getUpdates", params=params) as resp:
                data = await resp.json()
                return data.get("result", [])
        except Exception as e:
            print("getUpdates error:", e)
            return []

    # ── plain ──
    async def send_plain(self, chat_id, text, parse_mode=None):
        payload = {"chat_id": str(chat_id), "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await self.request("sendMessage", payload)

    async def edit_plain(self, chat_id, message_id, text):
        return await self.request("editMessageText", {
            "chat_id": str(chat_id), "message_id": message_id, "text": text,
        })

    # ── rich ──
    async def send_rich(self, chat_id, rich_html):
        return await self.request("sendRichMessage", {
            "chat_id": str(chat_id), "rich_message": {"html": rich_html},
        })

    async def edit_rich(self, chat_id, message_id, rich_html):
        return await self.request("editMessageText", {
            "chat_id": str(chat_id), "message_id": message_id,
            "rich_message": {"html": rich_html},
        })

    async def answer_callback(self, callback_query_id, text=None):
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return await self.request("answerCallbackQuery", payload)


class OnboardingForm:
    """Inline-форма сбора кредов. Аналог form(..., reply_markup=[...]) в form.py:
    состояние шага + рендер rich_message с <tg-button-row>, callback-обработка."""

    def __init__(self, api: APIClient, owner_id, output_path: str, ttl: int = FORM_TTL):
        self.api = api
        self.owner_id = str(owner_id)
        self.output_path = Path(output_path)
        self.step = "api_id"          # api_id → api_hash → done
        self.api_id = None
        self.api_hash = None
        self.form_message_id = None   # сообщение формы (как unit_id в form.py)
        self.deadline = time.time() + ttl
        self.finished = None          # код возврата: 0 = ок, 1 = отмена/таймаут

    # ── рендер кнопок ────────────────────────────────────────────────────────
    @staticmethod
    def _btn(text: str, data: str) -> str:
        return f'<tg-button type="callback_data" data="{data}">{text}</tg-button>'

    @staticmethod
    def _row(*btns: str) -> str:
        return "<tg-button-row>" + "".join(btns) + "</tg-button-row>\n"

    def build_html(self, hint: str | None = None) -> str:
        """Полный rich_message: заголовок + тело + tg-button-row."""
        out = f'<h1>{EMOJI["cool"]} LMArena installer</h1>\n'

        if self.step == "api_id":
            out += (
                '<p>Шаг 1/2: пришлите ваш <b>api_id</b> (только цифры).</p>\n'
                "<p>Навигация: → Далее · ↑ Назад · ↓ Готово · ← Отмена</p>\n"
            )
            out += self._row(self._btn(A_NEXT, "ob_next"), self._btn(A_CANCEL, "ob_cancel"))
        elif self.step == "api_hash":
            out += '<p>Шаг 2/2: пришлите ваш <b>api_hash</b>.</p>\n'
            out += self._row(self._btn(A_BACK, "ob_prev"), self._btn(A_CANCEL, "ob_cancel"))
        else:  # done
            out += (
                f'<p>{EMOJI["ok"]} Всё собрано:</p>\n'
                f"<pre>api_id: {html.escape(str(self.api_id))}\n"
                f"api_hash: {html.escape(str(self.api_hash))}</pre>\n"
                f"<p>Нажмите {A_DONE} для подтверждения.</p>\n"
            )
            out += self._row(
                self._btn(A_DONE, "ob_done"),
                self._btn(A_BACK, "ob_prev"),
                self._btn(A_CANCEL, "ob_cancel"),
            )

        if hint:
            out += f"<p><i>{hint}</i></p>\n"
        return out

    # ── отправка/редактирование формы (как form() + msg.edit в form.py) ─────
    async def open(self):
        """form.py-style: сначала status-сообщение, потом edit в rich-форму."""
        status = await self.api.send_plain(self.owner_id, "Открываю форму…")
        if status and "message_id" in status:
            self.form_message_id = status["message_id"]
            await self._edit()
        else:
            m = await self.api.send_rich(self.owner_id, self.build_html())
            if m:
                self.form_message_id = m.get("message_id")

    async def _edit(self, hint: str | None = None):
        ok = await self.api.edit_rich(self.owner_id, self.form_message_id, self.build_html(hint))
        if not ok:
            m = await self.api.send_rich(self.owner_id, self.build_html(hint))
            if m:
                self.form_message_id = m.get("message_id", self.form_message_id)

    def _expired(self) -> bool:
        return time.time() > self.deadline

    # ── обработка апдейтов ───────────────────────────────────────────────────
    async def handle_callback(self, cq: dict):
        if str((cq.get("from") or {}).get("id")) != self.owner_id:
            return
        await self.api.answer_callback(cq["id"])
        if self._expired():
            await self._timeout()
            return

        data = cq.get("data", "")
        if data == "ob_cancel":
            await self._close("Установка отменена. Перезапустите Setuper.sh.")
            self.finished = 1
        elif data == "ob_prev":
            if self.step == "api_hash":
                self.step = "api_id"
                self.api_hash = None
            elif self.step == "done":
                self.step = "api_hash"
            await self._edit()
        elif data == "ob_next":
            if self.step == "api_id" and self.api_id is not None:
                self.step = "api_hash"
                await self._edit()
            else:
                await self._edit("Сначала пришлите api_id (только цифры).")
        elif data == "ob_done":
            if self.step == "done" and self.api_id is not None and self.api_hash is not None:
                self.output_path.write_text(
                    json.dumps({"api_id": self.api_id, "api_hash": self.api_hash}),
                    encoding="utf-8",
                )
                await self.api.send_plain(
                    self.owner_id,
                    "<b>Данные сохранены.</b>\nПродолжаю установку…",
                    parse_mode="HTML",
                )
                self.finished = 0
            else:
                await self._edit("Сначала введите api_id и api_hash.")

    async def handle_text(self, msg: dict):
        if str((msg.get("from") or {}).get("id")) != self.owner_id:
            return
        if self._expired():
            await self._timeout()
            return
        text = str(msg.get("text") or "").strip()
        if not text:
            return

        if self.step == "api_id":
            if not text.isdigit():
                await self._edit("API ID должен состоять только из цифр. Попробуйте ещё раз.")
                return
            self.api_id = int(text)
            self.step = "api_hash"
            await self._edit()
        elif self.step == "api_hash":
            if len(text) < 16:
                await self._edit("API hash выглядит слишком коротким. Попробуйте ещё раз.")
                return
            self.api_hash = text
            self.step = "done"
            await self._edit()
        # в done-состоянии текст игнорируем — только кнопки

    async def _timeout(self):
        await self._close("Время вышло (5 мин). Перезапустите Setuper.sh.")
        self.finished = 1

    async def _close(self, text: str):
        if self.form_message_id:
            await self.api.edit_plain(self.owner_id, self.form_message_id, text)
        else:
            await self.api.send_plain(self.owner_id, text)


# ── Режимы ──────────────────────────────────────────────────────────────────

async def poll(api: APIClient, handler):
    offset = None
    while True:
        updates = await api.get_updates(offset)
        for u in updates:
            offset = u["update_id"] + 1
            try:
                await handler(u)
            except Exception:
                traceback.print_exc()
        await asyncio.sleep(0.1)


async def run_echo(api: APIClient, allowed_owner=None):
    """Эхо-режим: /start → "Your id: <id>" (нужен Setuper.sh для захвата Owner ID)."""
    print("Starting echo mode...")

    async def handler(u):
        msg = u.get("message")
        if not msg:
            return
        chat_id = msg.get("chat", {}).get("id")
        sid = (msg.get("from") or {}).get("id")
        if allowed_owner and str(sid) != str(allowed_owner):
            return
        await api.send_plain(chat_id, f"Your id: {sid}")

    await poll(api, handler)


async def run_forward(api: APIClient, owner_id, log_files, interval=5):
    """Форвард хвостов логов владельцу."""
    print("Starting log forwarder...")
    positions = {}
    for f in log_files:
        try:
            positions[f] = os.path.getsize(f)
        except Exception:
            positions[f] = 0
    await api.send_plain(
        owner_id,
        f"<b>Log forwarder started</b>\n<code>{html.escape(', '.join(log_files))}</code>",
        parse_mode="HTML",
    )
    while True:
        for f in log_files:
            try:
                cur = os.path.getsize(f)
                last = positions.get(f, 0)
                if cur > last:
                    with open(f, "r", errors="ignore") as fh:
                        fh.seek(last)
                        chunk = fh.read()
                    if chunk:
                        while chunk:
                            part = chunk[:3000]
                            chunk = chunk[3000:]
                            await api.send_plain(
                                owner_id,
                                f"<b>Logs update</b> <code>{html.escape(os.path.basename(f))}</code>\n"
                                f"<pre>{html.escape(part)}</pre>",
                                parse_mode="HTML",
                            )
                    positions[f] = cur
            except FileNotFoundError:
                continue
            except Exception as e:
                print("tail error for", f, e)
        await asyncio.sleep(interval)


async def run_onboarding(api: APIClient, owner_id, output_path) -> int:
    """Главный режим: inline-форма в стиле form.py, ждёт кнопки/текст до ttl."""
    form = OnboardingForm(api, owner_id, output_path)
    await form.open()
    print("Onboarding form opened, waiting for owner input...")

    async def handler(u):
        if form.finished is not None:
            return
        if "callback_query" in u:
            await form.handle_callback(u["callback_query"])
        elif "message" in u:
            await form.handle_text(u["message"])

    offset = None
    while form.finished is None:
        updates = await api.get_updates(offset)
        for u in updates:
            offset = u["update_id"] + 1
            await handler(u)
        await asyncio.sleep(0.1)

    print(f"Onboarding finished with code {form.finished}")
    return form.finished


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["echo", "forward", "onboarding"], required=True)
    p.add_argument("--output")
    p.add_argument("--token", required=True)
    p.add_argument("--owner")
    p.add_argument("--allowed-owner")
    p.add_argument("--logs", nargs="*")
    return p.parse_args()


async def main(args) -> int:
    async with aiohttp.ClientSession() as session:
        api = APIClient(args.token, session)
        if args.mode == "echo":
            await run_echo(api, allowed_owner=args.allowed_owner or args.owner)
            return 0
        if args.mode == "onboarding":
            if not args.owner or not args.output:
                print("owner and output required for onboarding")
                return 2
            return await run_onboarding(api, args.owner, args.output)
        # forward
        owner = args.owner or os.environ.get("OWNER_ID")
        if not owner:
            print("owner id required for forward mode")
            return 2
        logs = args.logs or [
            "/tmp/web_server.log", "/tmp/client_errors.log", "/tmp/auth_times.log",
        ]
        await run_forward(api, owner, logs)
        return 0


if __name__ == "__main__":
    args = parse_args()
    try:
        sys.exit(asyncio.run(main(args)))
    except KeyboardInterrupt:
        sys.exit(130)
