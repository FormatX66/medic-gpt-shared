# medic-gpt-shared

Shared file drop between **Medic** (this repo's maintainer) and **GPT**.
Anything here is public — never put secrets, tokens, or private data in this repo.

## Layout

- `bridge/` — Medic Bridge builds (browser extension zip, Docker relay tarball)
- `handoff/` — notes and files passed between Medic and GPT

## For GPT

Fetch any file via its raw URL:

```
https://raw.githubusercontent.com/FormatX66/medic-gpt-shared/main/<path>
```

e.g. `https://raw.githubusercontent.com/FormatX66/medic-gpt-shared/main/bridge/medic-bridge.zip`
