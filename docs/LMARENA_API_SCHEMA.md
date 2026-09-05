# LMArena Bridge API Schema

## OpenAI-Compatible Endpoints

### `POST /api/v1/chat/completions`
**Формат запроса (OpenAI-совместимый):**
```json
{
  "model": "Max | gpt-5.5-instant | gemini-3.1-pro-preview | ...",
  "messages": [{"role": "user", "content": "..."}],
  "stream": false,
  "modality": "text | image | search | webdev | video",
  "conversation_id": "da6f5a4edce18d8c"
}
```

**Формат ответа (OpenAI-совместимый):**
```json
{
  "id": "chatcmpl-<uuid>",
  "object": "chat.completion",
  "created": 1788370090,
  "model": "gpt-5.5-instant",
  "conversation_id": "da6f5a4edce18d8c",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Paris"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 5,
    "total_tokens": 55
  }
}
```

## Капабилити

| Капабилити | Modality | Model | Промпт | Статус |
|------------|----------|-------|--------|--------|
| Text | (auto) | Max | "What is..." | ✅ HTTP 200, content: "Paris" |
| Image | image | Max | "Generate a photorealistic image..." | ✅ HTTP 200, URL изображения |
| Search | search | gemini-3.1-pro-preview | "What is the latest news..." | ❌ 429 rate limit |
| WebDev | webdev | Max | "Create a landing page..." | ✅ HTTP 200, URL: https://<id>.arena.site |

## WebDev Особенности

- **a2: чанки**: `[{"type":"webdev","event":{"type":"init","files":[{"path":"index.html","contentType":"text/html","content":"..."}]}}]`
- **URL деплоя**: `https://{modelAMessageId}.arena.site` (modelAMessageId = uuid7, генерируется мостом)
- **Файлы**: index.html + assets (CSS, JS, изображения)
- **Время генерации**: 7-15 минут (452s-832s)
- **Reasoning tokens**: content содержит reasoning (до 17000+ токенов), отдельного поля нет в OpenAI-формате

## Follow-Up (Многоходовый диалог)

- conversation_id возвращается в ответе
- Для продолжения того же чата передать `conversation_id` в теле запроса
- Второй запрос идёт на `post-to-evaluation/{conversation_id}`
- Ограничение: session хранится в памяти моста (теряется при рестарте)

## Управление

### `GET /api/v1/health` → 200
### `GET /api/v1/models` → список моделей (313)
### `POST /api/v1/refresh-tokens` → обновление токенов/моделей