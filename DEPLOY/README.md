# LMArena DEPLOY

Утилиты управления и редеплоя LMArena Bridge. Первичная установка — не здесь,
а в `Storage/Installation/Setuper.sh`.

## Установка с нуля

```bash
curl -fsSL https://raw.githubusercontent.com/i-execute/Arena/main/Storage/Installation/QuickStart.sh | bash
```

Скрипт спрашивает **только BOT_TOKEN**. Всё остальное собирается внутри Telegram:
owner id (эхо-режим бота), `api_id`/`api_hash` (инлайн-инпут в `/setup`), лог-группа
(`/here` в группе). GitHub-токен запрашивается лишь если анонимная загрузка Camoufox
упёрлась в rate limit GitHub.

## Файлы

### `redeploy.sh`
Полный редеплой: git pull → restart systemd user services → health check.

```bash
./redeploy.sh            # полный цикл
./redeploy.sh --no-pull  # без git pull
./redeploy.sh --bridge   # только bridge
```

### `deploy.sh`
То же плюс режим `--status` (проверка всех 5 сервисов без изменений).

### `tunnel.sh`
Управление cloudflared-туннелями (Dashboard + API).

```bash
./tunnel.sh status          # статус + URL
./tunnel.sh url             # только URL (key=value)
./tunnel.sh restart [web|api]
./tunnel.sh start|stop
```

### `cloudflared_deployer.py`
Легаси-деплойер (cloudflared sites). Не рекомендуется для новых установок.

## Где что лежит

| Путь | Содержимое |
|---|---|
| `.env` (корень репо) | **все секреты**: BOT_TOKEN, BRIDGE_API_KEY, ARENA_AUTH_TOKEN, cf_clearance, JWT-секрет, api_id/api_hash. `chmod 600`, в git не попадает |
| `.env.example` | документированный шаблон |
| `WEB/data/config.json` | только несекретное runtime-состояние: модели, usage, id топиков, настройки браузера |
| `Storage/logs/` | `bridge.log`, `bot.log` |
| `Storage/sessions/` | сохранённые чат-сессии bridge |

Секреты **никогда** не пишутся в `config.json`: этот файл постоянно перезаписывается
фоновыми задачами, симлинкнут в корень репозитория и отражается в дашборде.
Читает/пишет их `BRIDGE/secrets_env.py` (приоритет: переменная окружения → `.env` → дефолт).

## Сервисы (systemd --user)

| Юнит | Что делает |
|---|---|
| `lmarena-bridge` | FastAPI :6767, OpenAI-совместимый API |
| `lmarena-web` | Node-дашборд :8787 (Telegram Mini App) |
| `lmarena-bot2` | Telegram-бот управления (Bot API + MTProto-слой) |
| `lmarena-web-tunnel` | cloudflared → :8787 |
| `lmarena-api-tunnel` | cloudflared → :6767 |

`lmarena-bot` (легаси-форвардер) **должен быть выключен**: он поллит тот же токен,
что и `lmarena-bot2`, и Telegram отвечает `Conflict: terminated by other getUpdates
request`. Setuper выключает его сам.

## Связь с ботом

- **Tunnels** → Dashboard + API URL, кнопка Restart перезапускает оба туннеля
- **Setup** → чек-лист конфигурации, инлайн-инпут для api_id/api_hash
- `/here` в группе → привязка лог-группы, создание топиков Logs + Requests
- В группах бот отвечает **эфемерно** (видно только тому, кто нажал); в ЛС — стрим
  Rich-драфтами с `<tg-thinking>`

## Важно

- Все сервисы работают через `systemctl --user` (никакого root/sudo, никаких `useradd`)
- После правки `BOT/lm_bot.py`: `systemctl --user restart lmarena-bot2`
- После правки `BRIDGE/*.py`: удалить `BRIDGE/__pycache__` и перезапустить bridge —
  устаревший `.pyc` иначе тихо переживает рестарт
- Логи: `journalctl --user -u lmarena-bridge -f`
