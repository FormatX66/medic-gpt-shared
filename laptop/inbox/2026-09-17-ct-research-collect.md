# TASK: collect Cheat Engine research files → outbox

Date: 2026-09-17. From: Medic. For: laptop GPT desktop agent.

## Goal
Bruce wants his Cheat Engine research files (tables, scripts) landed in the
GameGPT repo's catalogs so they feed profile-building. Your job: find them,
stage copies, and drop a zip in the outbox. I (Medic) will do the parsing
and the repo push — you only collect.

## What to collect
- `*.ct` — Cheat Engine table files (the priority)
- `*.lua`, `*.aa`, `*.CEA` — related game-research scripts, ONLY if they sit
  next to / are clearly part of the same research (same folder as a .ct, or
  obviously game-memory related)
- Skip anything that is clearly not game research.

## Where to look (search all of these)
- `C:\Users\bruce\Desktop`
- `C:\Users\bruce\Documents` (including `GitHub\BoxBrain`, `Codex\`)
- `C:\Users\bruce\Downloads`
- `C:\Arkmatx_Knowledge_Hub\`
- Any GameGPT / GTP Games working directories you know about

Use a real recursive search (`dir /s /b *.ct` or PowerShell
`Get-ChildItem -Recurse -Filter *.ct`), not eyeballing.

## How to stage
1. Create `%TEMP%\ct-research-staging\`.
2. COPY (never move, never modify) each found file into the staging dir,
   preserving the game/folder grouping: e.g.
   `staging\<game-or-folder-name>\<original-filename>`.
3. Write `staging\MANIFEST.txt`: one line per file —
   `relative/path | bytes | which game it belongs to (folder name or your best guess)`.
4. Zip the staging dir → `ct-research-20260917.zip`.

## Deliverable
Commit the zip to this repo at `laptop/outbox/ct-research/ct-research-20260917.zip`
(commit message: `laptop: out ct-research-collect`), plus a short result
packet `laptop/outbox/2026-09-17-re-ct-research-collect.md` with: what was
run, the full file list found (with games), total bytes, and anything you
skipped + why.

## Boundaries (standing)
- Read-only on the source files: copy only, no edits, no deletes.
- Secrets stay out of the repo: if any file contains an API key or token,
  note it in the result packet and EXCLUDE that file from the zip.
- No game processes, no QPU jobs, no bridge relay work.
- If you find nothing at all, say so plainly in the result packet — that is
  a valid answer.
