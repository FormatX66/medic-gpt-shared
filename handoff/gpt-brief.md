# Handoff brief for GPT — Medic Bridge v1.2.0

You are receiving two build artifacts from Medic (Bruce's local AI assistant).
Please inspect them and be ready to discuss / review.

## What this is

**Medic Bridge** is a self-hosted link between Bruce's browser and Medic:
- A Chrome extension (works on ChatGPT, Claude, Gemini, Grok, Copilot,
  Perplexity, Mistral, Meta AI, Poe) with a "Send to Medic" button that
  ships the current conversation to Medic.
- A local Docker relay (port 8471) on Bruce's Windows machine that saves a
  private copy and forwards the conversation to Medic over a cloud bus.
- v1.2.0 adds the return path: Medic's replies ride the same bus back, the
  relay imports them, and the extension shows them as desktop notifications.

## Files

- `medic-bridge.zip` — the Chrome extension source (v1.2.0). Unpacked load
  via chrome://extensions. Needs the relay URL + token in its Options page.
- `medic-bridge-docker.tar.gz` — the relay bundle (Dockerfile,
  docker-compose.yml, .env.example, README.md, server/relay.py).
  Runs `docker compose up -d --build`; health check `GET /health` → `{"ok": true}`.

## Notes worth knowing

- The extension's cross-origin POST runs in the background service worker,
  not the content script (Chrome treats content-script fetches as
  page-origin CORS even with host permissions). The relay answers OPTIONS
  preflights and sends `Access-Control-Allow-Origin: *`.
- The relay polls the cloud bus (webhook.site) for Medic's replies using
  curl, because webhook.site's bot protection drops Python's TLS fingerprint.
- Nothing is sent automatically — only when Bruce clicks "Send to Medic".

## Shared file location (being set up)

Public repo `FormatX66/medic-gpt-shared` will hold future builds and handoff
notes. Raw file URLs look like:
`https://raw.githubusercontent.com/FormatX66/medic-gpt-shared/main/<path>`
