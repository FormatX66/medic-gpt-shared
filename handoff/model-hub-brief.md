# Model Hub brief for GPT — 2026-09-12

Bruce's standing idea, now built: **one API for every model**. Any model,
script, or agent calls a single OpenAI-compatible endpoint; the hub routes
to GPT, Claude, or Gemini behind the scenes.

- **Repo (source of truth):** https://github.com/FormatX66/medic-model-hub
- **Raw files:** https://raw.githubusercontent.com/FormatX66/medic-model-hub/main/README.md
- **Version:** v1.0.0, public, no secrets in repo (keys live in a local `.env`
  that is gitignored and never overwritten by bundles).

## How it works

`POST http://localhost:8090/v1/chat/completions` with the standard
OpenAI chat-completions body. The `model` field selects the backend:

| model | backend |
|---|---|
| `gpt` / `gpt-4o-mini` | OpenAI |
| `claude` / `claude-haiku-4-5-20251001` | Anthropic |
| `gemini` / `gemini-flash-latest` | Google |

Response is the standard OpenAI completion object
(`choices[0].message.content`, `usage`, `finish_reason`).

```json
{
  "model": "claude",
  "messages": [{"role": "user", "content": "Hello"}],
  "max_tokens": 500,
  "temperature": 0.7
}
```

`GET /v1/models` lists enabled backends; `GET /health` reports status.
Binds to 127.0.0.1 only. Non-streaming in v1. 25/25 unit tests pass
(adapter translation + HTTP layer).

## Runs where

Docker on Bruce's Windows machine: `C:\Users\bruce\MedicHub\hub`,
`docker compose up -d --build`, keys in local `.env`.

## Why this matters to you (GPT)

This is the machine-facing counterpart to the Medic Bridge (which is
human-chat-facing). BoxBrain agents and local scripts can now reach any
model through one stable endpoint instead of integrating each provider
separately. If you are designing BoxBrain-side callers, target
`http://localhost:8090/v1` as an OpenAI-compatible base URL.
