# Voxwell: notes for agents

`CONTRIBUTING.md` is the rulebook: layout, licensing, tests, the checks before a PR. This file holds what the repo cannot tell you by looking.

## Clean room

Voxwell is the MIT rewrite of an AGPL app (`Troy2727/voxwell-agpl`, archived; local copy in `../voxwell`). Build every feature from a description and this repo's own code, so the AGPL source stays unread: no copying, no peeking for structure. A port from the old app is a fresh implementation with its own design.

## The website

`voxwell.vercel.app` is the `app/` build. It does no work itself; every call goes to the backend on the visitor's computer (README › The website).

- Which pages may call the backend: `APP_ORIGINS` in `backend/voxwell/origins.py`. It gates both CORS and the live-audio WebSockets, so one edit covers both.
- Chrome's Local Network Access: the visitor clicks Allow once. Headless Chromium cannot show that prompt, so automated runs pass `--disable-features=LocalNetworkAccessChecks` to stand in for the click.
- Deploys are manual (the Vercel project has no Git link):
  1. Build `app/` with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` set to the live site's values; without them the build ships with sign-in off.
  2. Deploy the built folder: `cd app/dist && VERCEL_ORG_ID=… VERCEL_PROJECT_ID=… vercel deploy --prod --yes`. The IDs come from `vercel teams ls --format json` and `vercel project inspect voxwell`. Deploying `app/` itself serves `app/public`, because of the project's output setting.
  3. `vercel alias set <deployment> voxwell.vercel.app --scope alex-mieses-projects`. That alias is manual and keeps pointing at the previous build until moved.
  4. Confirm the live `index.html` references the new `assets/index-*.js`.

## Shared registries

Every feature edits the same lists: `backend/voxwell/features/__init__.py`, `app/src/features/index.ts`, `cli.py`, `features/integrations/mcp_server.py` (`TOOLS` and `HANDLERS`), the `TOOLS` table in `app/src/features/integrations/Page.tsx`, `README.md`, `skills/voxwell/SKILL.md`, and the id lists in `backend/tests/test_core.py` and `backend/tests/features/test_integrations.py`. Parallel branches conflict there. Resolve by keeping both entries in registry order, then check that `mcp_server.TOOLS` holds one dict per tool and matches `HANDLERS`: a conflict inside a dict literal merges two tools into one. Counts on the Integrations page come from `TOOLS.length`; keep numbers out of the prose.

## Windows machine

- Norton re-signs HTTPS, so run uv with `UV_SYSTEM_CERTS=1`.
- The repo lives on OneDrive, where hardlinks fail (os error 396), so also set `UV_LINK_MODE=copy`.
- Point `VOXWELL_DATA_DIR` at a scratch folder when driving the real app, so tests leave the user's voices alone.

## UI checks

Before a UI PR, open every page with Playwright at 390, 768, 1024 and 1440 px wide and confirm `scrollWidth` equals the window width. Patterns that broke before:

- Buttons are `shrink-0`; a wrapping one needs `max-w-full`.
- Card header rows need `flex-wrap`.
- `TabsList` fixes its height through `group-data-[orientation=horizontal]/tabs:h-9`; a wrapping list overrides that exact selector.
- `SidebarInset` keeps `min-w-0`.
- Phone menu items call `setOpenMobile(false)`.

Live features can be driven with Chromium's `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>`.

## Known gaps

- **Speaker labels:** sherpa-onnx's segmentation step merged two clearly different voices into one speaker. Their embeddings separate cleanly (cosine 0.15), and the clustering threshold changed nothing. The likely fix is clustering per-transcript-segment embeddings and splitting segments where the speaker changes.
- **Sound effects:** these need the user's Hugging Face token, because Stable Audio Open is gated.

## Pull requests

One PR per change, using the `pr` body template. Merge with a merge commit once CI is green: backend tests on Windows, macOS and Linux, plus the frontend typecheck and build. No review bots run on this repo.
