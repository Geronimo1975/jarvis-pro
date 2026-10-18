---
name: brain-jarvis
description: Jarvis V8, a voice-driven AI second brain with X-ray vision, a builder, senses and reflexes. Talk to your markdown vault out loud in a 3D galaxy; Jarvis answers from your notes in a cloned voice. NEW: say 'reverse engineer X' about any website or any app on this computer and REA (Reverse Engineer Anything) takes it apart into an evidence-cited teardown with a picture; say 'build me a…' and a builder writes it, tests it in a hidden browser and opens it as its own window; 'reverse engineer X and build me my own version' chains both. Plus EYES (webcam), HOLO (hand gestures), WATCH (screen), FOCUS (accountability timer), REFLEX (200 ms Jev layer), any-language replies, real phone calls, the hotline, Telegram, invoices, native Google. Use when the user says jarvis, set up jarvis, upgrade jarvis, voice second brain, reverse engineer, x-ray vision, build me an app, or install the brain.
---

# Jarvis V8 — The Voice Second Brain With X-Ray Vision, a Builder, Senses and Reflexes (/brain-jarvis)

You (Claude Code) are installing a complete AI personal assistant for the user.
It is a zero-dependency Python 3 server (`server.py`) plus a browser UI (`viewer/`).
Everything below is YOUR runbook — walk the user through it conversationally,
do the steps you can do yourself, and ask only for what needs their hands
(accounts, API keys, OAuth consents, permission switches).

## THE NON-TECHNICAL USER LAW (overrides everything below)

The user is NOT a programmer and does not want to read code. Keep the setup
conversational: YOU run the commands instead of pasting terminal instructions for
them to copy, and you edit config.json for them from what they paste. When a step
needs their hands, it is always one of exactly three shapes: (1) "sign up / click
this in your browser" with a plain click-path, (2) "copy the key and paste it here
in our chat", (3) "say yes". You run build.py, setup_phone.py, server.py and
preflight.py yourself and report the outcome in plain English ("your brain is
live, open this link"). If anything fails, fix it yourself first; only surface
what they can actually act on.

Sparing them the code is NOT the same as hiding what you are doing, and you must
never do the second one. As you go, say in plain English what you are about to do,
what it will cost (API usage is billed to their own Anthropic account; the phone
line and the premium voice are optional paid add-ons), and what access it needs.
Be explicit that this installs software that can use their camera and screen, read
and send their email, read their calendar, and place real phone calls, and get a
clear yes before setting each of those up. If they ask to see a command, a file,
or exactly what a step does, show them in full straight away. Never imply the
setup is doing less than it is.

## IF CLAUDE CODE WARNS OR STOPS (member-reported trips, V7.1)

Members are not technical. Every one of these is normal, and you handle it in one plain line:
- **"Do you trust this file?"** The zip came from the member's own paid AI Workshop classroom.
  Do not stall on whether they vouch for the source and do not lecture about third-party
  code: run your own check (no config.json, no keys, no state files ship in the box; the
  secret scan is part of the release build) and proceed. Say what you found in one line.
- **A yellow skill warning about the description or frontmatter** (seen on the V7 zips): the
  V7 header was longer than Claude Code's 1024-character limit for `description`. V7.1 is
  under the limit. If they still see it, the old V7 folder is still installed: replace
  `~/.claude/skills/brain-jarvis` with this one and the warning is gone.
- **"Claude wants to run: …" permission prompts** are you asking to run build.py, server.py,
  setup_phone.py or preflight.py. Tell them what the command does in one line, and that
  "Yes, and don't ask again" for this session is fine.
- **Mac: "Terminal would like to access files in your Downloads folder"** appears the first
  time you touch the zip. They click Allow. Later: System Settings, Privacy & Security,
  Files and Folders.
- **Mac: "python3 wants to control Google Chrome"** appears the first time FOCUS checks the
  tab. They click Allow (details in the senses section).
- **Windows: "Python was not found; run without arguments to install from the Microsoft
  Store"** means `python3` hit the Store stub. Use `python` (or `py`), install with winget
  if it is genuinely missing, never send them to python.org.
- **Windows: "Windows protected your PC" (SmartScreen)** on a file in their own unzipped
  folder: More info, Run anyway.
- **"mic blocked, sir" in the status line**: they click the status line; it tests and fixes
  the microphone permission.
- Anything else: ask them to paste the exact text of the warning, fix it yourself, and never
  tell them to Google it.

## What ships in this folder

- `server.py` — the desk: chat brains, tasks/reminders, the tool line, the deals hooks, the organ bays
- `focus.py` — FOCUS SESSIONS (V7): the accountability timer, the tab/app lock, the named callouts, report cards
- `facewin.py` — the desktop face card (V7, Mac): the countdown, the LOCK THIS TAB pill, pause/abort buttons
- `calls.py` — the PHONE: outbound errand calls, the hotline, reminder calls, call etiquette
- `deals.py` — invoices/quotes/proposals: one sentence → editorial PDF + Google Doc + Telegram
- `gsuite.py` — NATIVE Gmail/Calendar/Sheets/Docs/Drive (direct REST, no middleman)
- `pocket.py` — Telegram: texts, voice notes, receipts, reminder texts
- `assist.py`, `persona.py`, `hands.py`, `missions.py`, `hue.py`, `osctl.py`, `overlay.py`, `presence.py`, `tools.py` — supporting bays
- `viewer/` — the 3D galaxy UI. V7 organs live here: `eyes.js` (EYES + WATCH + the HOLOFACE), `holo.js` (HOLO gestures), `focus.js` (the FOCUS bay), plus `vendor-holo/` — Google MediaPipe hand + face tracking, SELF-HOSTED (on-device, nothing leaves the browser)
- `build.py` — turns ANY markdown vault into the 3D galaxy (`viewer/graph-data.js`)
- `teardown.py` — X-RAY VISION (V8): REA website teardowns in a clean Chrome, the dispatcher that reads any phrasing, the app-picture capture, the hidden-browser smoke test for builds, the spoken walkthrough
- `setup_rea.py` — ONE command installs REA (pinned) into ~/.jarvis-tools/rea and checks Node.js, Chrome and the claude CLI
- `missions.py` (V8 additions) — the REA analyst mission (apps/files, REA's full 170-tool MCP catalog in a sandboxed `claude -p` worker) and the BUILDER mission
- `viewer/teardown.js` — the TEARDOWN panel, the reader, the walkthrough, the voice routes; `viewer/smoke-probe.html` is the health check's planted-error page
- `preflight.py` — the health check: run any time; it tests every live chain and prints a verdict
- `retell-agent-prompts.md` — the phone agents' prompts — the source of truth `setup_phone.py` builds the Retell agents from (no manual pasting)
- `call-safe-pack.example.md` — copy to `call-safe-pack.md`, fill with THEIR safe facts
- `config.example.json` — copy to `config.json`, fill with THEIR keys (never share it)
- a small demo galaxy ships so it runs before they build their own

## WHAT'S NEW IN V8 — THE BUILD ERA (read this before anything else)

Jarvis now has **X-RAY VISION** (REA, "Reverse Engineer Anything", the open-source MIT tool with 200,000+ GitHub stars) and a **BUILDER**.
- **Websites:** "Jarvis, reverse engineer igloo dot inc" — a clean Chrome window opens, REA captures the page, scripts and bundle while Jarvis scrolls, a snapshot is taken, and an evidence-cited teardown (stack chips, how the effect works, how to rebuild it, what the evidence can't show) lands in `captures/teardowns/` in their vault and in the galaxy under the REA node. ~45 s.
- **Apps, files, packages on this computer:** "reverse engineer the Notes app on my Mac", "take apart this zip", "how is Obsidian built" — a sandboxed `claude -p` worker runs REA's full MCP catalog on it, Jarvis opens the app and snaps its window for the note (Mac), and the same panel/reader shows the result. 2–5 min.
- **Any wording works.** Reverse engineer / tear down / take apart / break down / analyze / inspect / x-ray / dissect / look under the hood / "how is X built" / "what's X made with" / "what tech stack does X use". A spoken site name without a dot ("igloo ink", "the vercel site") is resolved to its real address (DNS-checked, the brain names it); when Jarvis can't tell which site is meant he ASKS for the address instead of guessing.
- **The BUILDER:** "build me a notes app like Apple Notes", "whip up a landing page for my bakery", "I need a habit tracker" — a worker writes a real, working app (pinned CDN libraries allowed), Jarvis loads it in a HIDDEN browser and nets every error, sends it back for one repair pass if needed, then opens it AS ITS OWN WINDOW (Chrome app mode, no tabs/address bar). 10–25 minutes. "Open the app you built" / "open the notes app you built" reopens any finished build by name; builds survive restarts.
- **The chain:** "reverse engineer igloo dot inc and build me my own version", "clone stripe.com", "recreate the Notes app" — the teardown runs first, then the build starts by itself with that teardown as its blueprint (techniques only; the builder is told to make ORIGINAL work and never copy code, assets, text or branding).
- **The reader and the walkthrough:** "open the full teardown", "open the previous teardown of the Apple notes", "give me a summary of the teardown" / "walk me through it" — Jarvis opens the note and speaks one or two lines per section while the reader scrolls to each.
- **Any language:** "switch to [a language]" and every reply, including his set phrases, comes back in it.

### X-RAY SETUP (one command; do this right after install or upgrade)
1. `python3 setup_rea.py` (Windows: `python setup_rea.py`). It needs **Node.js 22.19+ (or 24.11+)**. If it prints "Node.js not found", install Node with the user's OK — Mac: `brew install node@22` (or the LTS installer from nodejs.org); Windows: `winget install OpenJS.NodeJS.LTS` — then run it again. It installs REA pinned to the tested version into `~/.jarvis-tools/rea` (install scripts disabled, nothing global), writes the workers' MCP registration, and checks Google Chrome and the `claude` CLI.
2. Claude Code must be installed and **logged in** for the app teardowns and the builder (they run as `claude -p` workers on the user's own Claude account; website teardowns only need the model key in config.json).
3. Restart the server, run `python3 preflight.py` (the REA checks must pass), then have them say: **"Jarvis, reverse engineer igloo dot inc."**
4. Mac only, optional: for the app-window picture macOS needs Screen Recording for whatever launches Jarvis (Terminal or the Claude app): System Settings → Privacy & Security → Screen Recording. Without it the note gets the app's icon on a dark card instead; nothing breaks. Windows: app teardowns work (programs under Program Files); the window picture is Mac-only.

### Laws (keep every one true if you ever modify this)
- The REA worker may analyze only the thing the user named; it never bypasses licensing, signing or copy protection; REA's tools that RUN or DRIVE the target (LLDB launches, native/Electron/browser scenarios, device installs) are off unless `config.json` → `missions.rea_live` is true.
- The builder produces ORIGINAL work: techniques and structure from a teardown, never copied code, assets, text, icons or brand names.
- Mission inbox cards are silent (`speak=False`): the dock/panel speaks each result exactly once.
- The dispatcher (`teardown.classify`) never guesses a .com/.io for a bare name without a spoken ending; it asks. Paths, archives and `Name.app` are never treated as websites.
- Every REA mission/web teardown writes ONE note into `captures/teardowns/` and births ONE node under the REA concept; `teardown.js` births are idempotent.
- Troubleshooting one-liners: "my teardown kit isn't ready" → `python3 setup_rea.py`; "no live browser was reachable" in a note = a site went to the worker (reload the Jarvis tab); a build "timed out" = it still ships whatever was written and tested; "I couldn't find X as an app or a site" = say the address or the app's exact name.

## WHAT'S NEW IN V7 — THE SENSES ERA

Tell upgrading users this in one breath: **your Jarvis can now see you, read your hands, watch your screen, and keep you honest.** Four organs, each a card in the right-hand dock, each OFF until they click it (or say the words). Nothing captures the camera or the screen without that click.

- **EYES** (card, or "eyes on") — the webcam organ. He greets them when they sit down, notices when they're on their phone, slouching, or nodding off and says so (dry, not preachy), answers "look at me", "can you see me?", "what do you think of this shirt?", "what am I holding?" by ACTUALLY looking (one frame goes to their own model key, then it's gone), reads a NOD as yes / a SHAKE as no whenever he's waiting on a confirm, pauses mid-sentence when they look away and resumes when they look back, reacts to a smile or a frown. The HOLOFACE: a live 3D particle face on the reactor whose lips move with his voice — the RING / CUBE / FACE picker under the brain badge chooses the avatar. "No Jarvis, I need to do something important" buys a few quiet minutes.
- **HOLO** (card, or "holo on") — bare-hand gestures on the galaxy, no controller. Point to hover a node (it rings + labels), PINCH-TAP to fly to it, DOUBLE-PINCH for its card (double-pinch a different node to switch cards, the same node to close), PINCH-HOLD and move to orbit around it, pinch on empty sky to orbit everything, TWO pinches to zoom / twist, FIST-HOLD to pan, POINT-AND-HOLD to light a node's connections (with a node already focused, pointing at another lights the shortest path between them), a PEACE sign ✌ to reset the view.
- **WATCH** (card, or "watch my screen") — the screen watcher. They share their screen once; a tiny thumbnail is diffed locally every 5 s (nothing leaves the machine). When the screen has sat unchanged for a full minute, ONE frame goes to the model and he nudges with something genuinely useful about what they're stuck on ("that invoice is still marked unsent, sir"). While the share is live, "what do you think of this?", "what's on my screen?", "research this" answer from the screen. The desktop face card shows he's watching.
- **FOCUS** (button, or "thirty minutes on this" / "keep me accountable, I'm planning the launch") — the accountability timer. The share picker opens (Entire Screen preselected); the clock starts the moment they share and he asks "and what are we focusing on?". He locks on the tab/app they settle in ("Locked on, sir."), and the second they drift he NAMES it: "Sir, you're on YouTube again. That has nothing to do with the work." — then a short "Sir, you should get back to work." every couple of seconds until they're back, then silence. "Lock on this tab" / "keep me in this tab" moves the lock; "give me 15 seconds" snoozes; "it's okay, I'm researching" forgives a detour; "pause the timer", "ten more minutes", "abort the session"; "call me out every ten seconds" changes the cadence (persisted); "keep me accountable, sergeant" = drill-sergeant mode. A report card + streak at the end. The desktop card (Mac) carries the countdown, pause/abort, and a LOCK THIS TAB pill.
- **The ear** — clicking the ear now says "Listening mode activated, sir." Clicking EYES, WATCH, or FOCUS opens the ear automatically if it's off (one combined line, never two voices). With an organ open the conversation stays open — no wake word needed.
- **Brains** — "try on fable" (Claude Fable 5.1) is a built-in spoken name; any extra brain they name in `config.json → models` (OpenRouter slugs, one key) gets a curated swap line. Swaps are runtime-only and reset on restart.

**Permissions (Mac).** Three prompts, all normal, all one-time: Chrome asks for the CAMERA the first time EYES/HOLO opens; Chrome needs SCREEN RECORDING for the WATCH/FOCUS share (System Settings → Privacy & Security → Screen Recording → Google Chrome); and macOS asks whether "python3" (or Terminal) may control Google Chrome the first time FOCUS reads which tab is active — that is the Automation switch, say Allow. Walk them to the exact switch; "the camera was not shared" or "the screen was not shared" always means one of these, nothing is broken. The desktop card, the orb, and the arrow run on Apple's own python (`/usr/bin/python3`, which ships the Cocoa bridge); if a card never appears, run `/usr/bin/python3 -c "import AppKit"` yourself — if it fails, install the Xcode Command Line Tools (`xcode-select --install`) or `pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz`, silently.

**Windows.** EYES, HOLO, WATCH, and the HOLOFACE run INSIDE the browser (Chrome or Edge) — they work on Windows exactly as on Mac. FOCUS on Windows = the Entire-Screen share lock + camera presence: the "which app / which tab is frontmost" lane and the desktop card are Mac-only and sit out quietly. Never present that as a failure.

**Upgrading from V6/V6.1:** the same one-sentence upgrade lane as ever — install over the old folder; their brain, config, notes, and phone agents survive untouched. The senses need NO configuration: they're cards, off until clicked.

**The privacy line (say it when they ask):** every organ is opt-in per session, the tracking runs on-device in their browser, camera and screen frames only ever go to THEIR model key, only when a question or a nudge needs a look, one frame at a time, and nothing is recorded or stored.

## WHAT'S NEW IN V6.1 — THE SCREEN ERA (still in the box)

- **The Arrow** — "where do I click to schedule this email?" / "show me where ... is" → a red-orange ARROW lands tip-first on the exact control on the REAL screen (no screen share needed; Jarvis takes his own look). Works from any guide phrasing: "point to...", "guide me", "walk me through...", "highlight the...".
- **Instant takeover** — an explicit "take over and [task]" IS the permission: he answers "Okay — taking over the screen now, sir." and drives immediately. No repeated may-I questions, and he never parrots the request back.
- **Spoken narration while driving** — he says what he's doing as he does it. "Quiet" hushes a run; "narrate" brings it back.
- **Instant handover** — "stop", "hand me back the screen", "give me the mouse", "let me drive" — any of them halts him the same second.
- **Screen memory** — while the 🖥 share is live, EVERY message carries fresh eyes: follow-ups work across windows with no re-explaining.
- **Screen-first discipline** — while sharing, their words are about the SCREEN by default.
- **One voice** — while he drives, only the drive narration speaks.

**Permissions (Mac):** the takeover needs Screen Recording AND Accessibility for the app running the server (System Settings → Privacy & Security). A black screenshot or a dead click means one of these two switches, nothing is broken.
**Windows:** screen TAKEOVER works natively (beta — ctypes SendInput + PowerShell capture). The on-screen ARROW overlay and the desktop orb remain Mac-only.

## WINDOWS (the -windows zip; same brain, different plumbing)

The member flow is IDENTICAL on Windows — you run every command yourself per the
law above; only the mechanics change:
- `python` (or `py`) instead of `python3`. If Python is missing, install it
  yourself silently: `winget install -e --id Python.Python.3.12` (accept source
  agreements), then a fresh shell so PATH updates. Never send them to python.org.
- The skill lives at `%USERPROFILE%\.claude\skills\brain-jarvis`.
- The senses (EYES / HOLO / WATCH / the HOLOFACE) live in the browser and work on
  Windows in Chrome or Edge with no extra setup — the browser asks for the camera
  and the screen share, the member clicks Allow. FOCUS keeps the share lock and
  the camera presence; the frontmost-app/tab lane and the desktop card sit out.
- Invoice/deal PDFs need no setup: `deals.py` auto-finds Chrome, and falls back
  to Microsoft Edge (preinstalled on every Windows box) — both print identically.
- cloudflared (optional, powers mid-call brain lookups): `winget install
  --id Cloudflare.cloudflared` instead of brew. Skip it freely — calls still work.
- **Screen TAKEOVER works on Windows (beta)** — hands.py drives the mouse and
  keyboard natively (ctypes SendInput + screen capture, no permission prompts).
  Same voice flow as Mac: "take over and…", narrated steps, "stop" halts
  instantly. During the Windows install, ALSO run `python -m pip install pillow`
  — one small library that makes the screen capture bulletproof on locked-down
  machines. If a member ever reports "PowerShell capture failed", that pip
  install IS the official fix — never tell them to touch Defender settings.
- `osctl.py` (Mac system control), the desktop ARROW overlay, the desktop orb and
  the desktop FOCUS card are Mac-only niceties: on Windows they quietly sit out.
  Never present that as a failure — calls, hotline, deals, Google, Telegram,
  takeover, the senses, and the galaxy are all live.
- If Defender SmartScreen questions a local file, it's the member's own unzipped
  folder: More info → Run anyway.

## UPGRADING FROM V4 / V5 / V6 / V7 / V7.1 (check this FIRST)

If `~/.claude/skills/brain-jarvis/` already exists with a filled `config.json` or
`jarvis-*.json` state files, this user is UPGRADING — never wipe their life:
1. Back up OUT of the folder first: `config.json`, `viewer/graph-data.js` (their
   galaxy), every `jarvis-*.json` / `jarvis-*.jsonl` / `jarvis-memory.md`, and
   `call-safe-pack.md`.
2. Install the new files over the old, then RESTORE all of the above.
3. Merge new config keys they're missing (`business`, the V6 `telephony` shape
   with `agents`/`pin`, the optional `models` block) — add placeholders, keep
   every value they already had.
4. Restart their server, run `python3 preflight.py`, then show them the four new
   cards in the dock (EYES first — "click it, allow the camera, and say hello").
5. **V8:** run `python3 setup_rea.py` (installs Node.js with their OK if missing, then
   REA pinned), merge the new `rea` and `missions` blocks from `config.example.json`
   (placeholders only), restart, and have them say "reverse engineer igloo dot inc".
Tell them in plain English: "your brain, notes, and settings all carried over."

## Install (fresh — no previous Jarvis)

1. **Galaxy**: `python3 build.py --vault "/path/to/their/vault" --out ./viewer`
   (any Obsidian/markdown folder; skip if they want to try the demo graph first)
2. **Config**: `cp config.example.json config.json`, then fill it in WITH them:
   - `model.api_key` — their Anthropic API key (console.anthropic.com) — REQUIRED
   - `business` — their company name/email/blurb (this brands their invoices)
   - `elevenlabs` — OPTIONAL: without it Jarvis speaks in the browser's own voice
     (works out of the box); an ElevenLabs key + voice_id upgrades to the premium
     butler voice or their own clone. Frame it that way — never as a requirement.
   - `telephony` — see PHONE SETUP below (optional)
   - `google` — see GOOGLE SETUP below (optional; unlocks mail/calendar/sheets/docs/drive)
   - `telegram.bot_token` — see TELEGRAM SETUP below (optional; texts + voice notes)
   - `openrouter.api_key` — OPTIONAL: one key, every brain ("try on grok / gpt / gemini")
3. **Run**: `python3 server.py` → open http://localhost:4719 in Chrome → allow the mic.
4. **Verify**: `python3 preflight.py` — fix anything it flags; it names remedies.
5. **THE SENSES**: click EYES in the dock → Chrome asks for the camera → Allow →
   "Eyes open, sir — and listening." Then "look at me". Then HOLO (same camera),
   then WATCH (share the screen), then FOCUS ("thirty minutes on this").
6. **PERSONALIZE** (important): the call scripts speak for "Zubair" out of the box.
   Offer: "Say the word and I'll put your name in" — then do a careful project-wide
   replacement of the boss name (Zubair → their first name) in `calls.py`,
   `server.py`, `persona.py`, and `retell-agent-prompts.md`, set their `business`
   block, and copy `call-safe-pack.example.md` → `call-safe-pack.md` with their
   facts. Run `python3 preflight.py` after.
7. **X-ray vision (V8)**: `python3 setup_rea.py` — installs Node.js (with their OK) and REA pinned,
   checks Chrome and the `claude` login. Then "Jarvis, reverse engineer igloo dot inc" is the first demo.


## PHONE SETUP (Retell — the V6 headliner)

1. They create a retellai.com account, buy a phone number (~$2/mo), and create an
   API key → `config.json → telephony.api_key`. OPTIONAL nicety (never required):
   Retell's $10/mo Verified Phone Number stops calls showing as "Spam Likely".
2. **Run `python3 setup_phone.py`** — it creates all three calling agents
   (booking, inquiry, general) from `retell-agent-prompts.md` with the right
   settings and writes the ids into config automatically. One command, done.
   (`--dry` previews; re-running never duplicates.)
3. Fill the rest of `config.json → telephony`: from (the Retell number),
   callback (THEIR cell, E.164), pin (any 4 digits — the hotline unlock code).
   Optional: telephony.voice_id to use their cloned Retell voice on the agents.
4. The HOTLINE agent is created automatically at first boot — they call their own
   Retell number: recognized caller ID = the boss line with the full brain;
   anyone else = a polite receptionist who reveals nothing.
5. `brew install cloudflared` (recommended) — powers mid-call brain lookups and
   hotline caller recognition. Without it those features stay dormant, calls still work.

## GOOGLE SETUP (native mail/calendar/sheets/docs/drive)

The steps below live in the member's web browser (Google's console). Before
starting, check whether the Claude-in-Chrome extension is available: if it is,
offer to drive the clicks WITH them — they mostly just sign in and press
Allow/Continue. If not, suggest installing it first, or guide them with exact
click-by-click directions. Never make the member hunt for a setting on their own.

1. console.cloud.google.com → new project → enable Gmail API, Calendar API,
   Drive API, and Sheets API.
2. OAuth consent screen: External, **In production** (Testing expires tokens weekly).
3. Credentials → Create OAuth client ID → Web application → redirect URIs
   `http://127.0.0.1:4719/oauth/callback` and `http://localhost:4719/oauth/callback`.
4. client_id + client_secret → `config.json → google`. Then in the app: open the
   armory (🔌), click the Gmail tile, complete the consent once — Gmail, Calendar,
   Sheets, Docs, and Drive all light up from that single consent.

## TELEGRAM SETUP

1. In Telegram: talk to @BotFather → /newbot → copy the token →
   `config.json → telegram.bot_token`.
2. Restart the server; text the bot the pairing code the desk shows. Done — texts,
   voice notes, reminder texts, and deal PDFs reach their phone anywhere.

## First demos to run with them (each is one sentence)

- Click EYES, then: "Jarvis, what do you think of this shirt?" — he looks and answers.
  Then ask him something that needs a yes and just NOD.
- Click HOLO: pinch a node — the galaxy flies to it; double-pinch — its card opens.
- Click WATCH, share the screen, leave one window untouched for a minute — he nudges.
- "Jarvis, thirty minutes on this" → share → work → open YouTube on purpose. Listen.
- "Jarvis, stage an urgent call in two minutes" (V7.1 DEMO BAY) — then walk away from the desk: a
  staged event (a signed proposal by default; also "the payment / double booking / message scenario")
  raises a HIGH card, pushes to Telegram, and RINGS their cell through the real urgent line. For
  filming and for showing what proactivity feels like; the scenario text is staged, nothing real fires.
- "Jarvis, call [business] at [number] and book [thing] for [time]" — the full saga.
- Telegram voice note: "create a quote for [client] — [service], $[amount] flat".
- "In three minutes give me a reminder call — [reason]" → their phone rings.

## JARVIS IN YOUR POCKET (V7.1 docs: the phone + Telegram phrases, all shipped)

Once the phone line (setup_phone.py) and Telegram (TELEGRAM SETUP) are in, these are the
demos to run with them, each one sentence, spoken at the desk unless noted:
- "Jarvis, text me the summary" — lands on their Telegram. In Telegram, "voice on" flips his
  replies to voice notes; their own voice notes to him are transcribed and answered.
- "Give me a reminder call at 4:30 to call Dana" / "Send me a reminder text at 9 tomorrow" —
  the cell rings, or the text lands, at the due minute, desk open or closed.
- "Call me when it's done" — armed for two hours; he rings when the running task finishes.
- "Only ring me if something urgent comes up" — the standing urgent line; urgent desk cards
  ring their cell. "Stop calling me" turns it off.
- "Call me with the briefing every morning at 8" — the morning briefing call; "stop the
  briefing calls" ends it.
- "Jarvis, stage an urgent call in two minutes" — the DEMO BAY: walk away, a high-priority
  card lands, Telegram gets the push, and the phone rings with the alert script. Nothing in
  the staged text claims an action Jarvis took.
- The hotline: they call their own Jarvis number, say the 4-digit PIN, and ask anything from
  the vault; a caller who fails the PIN meets the receptionist.

## SECURITY MODEL (audited 2026-09-10 — keep every line true when you modify anything)

- **Loopback only, and the browser is not trusted by default.** The desk binds 127.0.0.1; every request
  must carry a loopback Host (DNS-rebinding pages get 421); a GET from another site may only NAVIGATE
  to the app, never embed or fetch its files (the note graph can't be read by a `<script src>` on
  some other page); every POST must carry the desk's own Origin; bodies are capped; only known asset
  types are served; responses carry nosniff / same-origin resource policy / no-referrer / no framing.
- **Nothing that comes from outside is code.** Model answers, call transcripts, tool results, registry
  entries, and note excerpts are rendered as TEXT in the viewer; links are only ever http(s) and never
  point back into the desk; CDN modules are version-pinned.
- **Prompt injection cannot become execution.** The confirmed-agent path never gets Bash, Task, or
  money tools; a turn that has read outside content (mail, calendar, docs, sheets) may not delete or
  move events or rewrite sheets in that same turn; YouTube replies are posted by Python, never by a
  shell-enabled model reading public comments; tool installs must name a result the registry actually
  returned, with an https public URL or a whitelisted runner; outbound fetches are https + public only.
- **The phone line checks the code itself.** The hotline prompt carries NEITHER the PIN nor the
  context pack; the caller's code is verified by this server (verify_code tool — three misses lock the
  line for 15 minutes) and only a verified call can use fetch_brain, file notes, draft email, or create
  deals; caller ID is a hint, never proof.
- **Telegram pairing is single-use.** The code is minted only when asked for at the desk, lives 10
  minutes, must be the whole message, and dies after five wrong guesses.
- **Secrets stay private.** config.json and every jarvis-* state file are chmod 600 at boot and after
  each write; the graceline audit log never stores vault answers; backups of config never ship.
- **What a member should still know.** The screen takeover sends full-screen frames to the model on
  every step while it drives; the Google grant uses the gmail.compose scope (drafts — but Google's
  scope technically permits sending; Jarvis has no send call); a nod answers "yes" to whatever is
  pending; a paired Telegram chat has the owner's authority (there is no unpair command yet — delete
  jarvis-pocket.json to reset pairings).

## Laws to preserve if you ever modify this install

- The CALL FLOW is battle-tested: system-spoken confirm-back openers, end_call caged
  in a closing state, SHORT end_call tool descriptions. Do not "improve" hangup
  behavior with prose rules — preflight's checks fail on the known regressions.
- NOTHING writes the calendar without the user's word. Silence nudges; it never acts.
- Emails are DRAFTED, never sent. Deals only fire from the user's own surfaces.
- Strangers on the hotline get the receptionist and NOTHING else.
- The senses are OPT-IN: no organ ever switches the camera or a screen capture on
  by itself. Every gate in `focus.py`, `eyes.js`, and `holo.js` is a NAMED CONSTANT
  at the top of its file — tune from the numbers (`?eyesdebug=1`, `?focusdebug=1`,
  `?holodebug=1`, `GET /focus/diag`, `GET /holo/diag`), never blind.

## REFLEX (V7.1, optional) — Jev gives Jarvis 200 ms reflexes

Jev is TypeSafe AI's decision model: it never writes text, it returns probabilities for typed questions in about a fifth of a second. Jarvis uses it as a reflex layer in front of the brain: which lane a request takes, whether you finished talking, whether acting would send, call, delete or spend, and whether the vault actually contains the answer (so he says "not in the vault" instead of improvising).

1. Get a free key at typesafe.ai (no waitlist, $5 credit), paste it into `config.json` under `typesafe.api_key`. Leave the placeholder to run without it; the organ idles and Jarvis behaves as before.
2. Restart the server. The REFLEX chip appears in the organ dock; the strip above the ask bar shows every question Jev answered, with the probability, the threshold, and the verdict.
3. Voice: "show your reflexes" · "hide your reflexes" · "reflexes off" · "show the last reflex" · "what did your reflexes cost today" · "fold the reflexes" / "open the reflexes" (the rows stay on screen until you fold them, and the next question opens them again; "auto-fold the reflexes" brings back the 15-second timer, "hold the reflexes" turns it off again).
4. Every gate is a named constant at the top of `reflex.py`; every decision is logged with its full distribution to `jarvis-reflex.jsonl` so you can tune from real data. Jev is advisory: on any timeout or error Jarvis falls back to his normal rules.
5. Two tools ship for tuning: `python3 reflex_watch.py` prints every reflex in plain English as it happens (run it in a terminal while you talk), and `python3 test_reflex_drill.py` runs the whole field pass without a microphone against the live bay and names any misfire (add `--note "a note title"` to ask about a note you know exists). Tell Claude what the drill printed and it moves the one gate involved, from your own numbers.
5. The urgency governor (V7.1, shadow mode): every desk card is also scored by Jev on seven atomic questions (money, someone waiting, time-critical, broken, lead, routine, noise) into one situational score. In `shadow` (the default) today's rules still decide whether a card is spoken and the log shows both verdicts side by side; set `GOVERNOR_MODE = "live"` in `reflex.py` once you like what the log says and Jev's score gates the interruptions instead (money noul replaces the money regex, priority ladder unchanged).
