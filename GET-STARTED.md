🏗️🧠 AI Second Brain **V8: THE BUILD ERA**. Your assistant can now take things apart and build, and still sees you, reads your hands, watches your screen and keeps you honest (JARVIS). Mac & Windows
This is the full system from the video, and you don't need to touch a single line of code. You download one file, and Claude installs and sets up everything FOR you. You just talk.

✨ **What's new in V8**

* 🔬 **X-RAY VISION (REA)**: say `reverse engineer igloo dot inc` and a clean Chrome window opens, REA takes the site apart while Jarvis scrolls, and an evidence-cited teardown (the stack, how the effect works, how to rebuild it, what it can't show) lands in your vault with a snapshot, in about 45 seconds. Any wording works: tear down, take apart, break down, analyze, "how is X built", "what's X made with".
* 💻 **Apps too**: `reverse engineer the Notes app on my Mac`, `take apart this zip`, `how is Obsidian built`. Jarvis opens the app, snaps its window for the note, and REA's full toolkit (170 tools) does the analysis in a sandbox. A few minutes.
* 🏗️ **The BUILDER**: `build me a notes app like Apple Notes`, `whip up a landing page for my bakery`, `I need a habit tracker`. He writes it, tests it in a hidden browser, fixes what broke, then opens it as its own window. `Open the app you built` brings any finished build back.
* 🔁 **The chain**: `reverse engineer igloo dot inc and build me my own version`, `clone stripe.com`. Teardown first, then the build starts by itself with that teardown as the blueprint. Original work, never a copy.
* 📖 **Read it, hear it**: `open the full teardown`, `open the previous teardown of the Apple notes`, `give me a summary of the teardown` / `walk me through it` (he reads a line or two per section while the reader scrolls).
* 🌍 **Any language**: `switch to [a language]` and every reply comes back in it.

✨ **What's new in V7**

* 👁️ **EYES: he can see you**: click the EYES card, allow the camera, and he greets you when you sit down, notices when you're on your phone or slouching, and answers "what do you think of this shirt?" or "what am I holding?" by actually looking. Nod for yes when he's waiting on you. Look away and he pauses mid-sentence, look back and he continues.
* 🫥 **The HOLOFACE**: a live 3D face made of particles on the reactor, lips moving with his voice. Pick RING, CUBE, or FACE under the brain badge.
* 🖐️ **HOLO: bare-hand control of the galaxy**: point to hover a note, pinch to fly to it, double-pinch to open its card, pinch and hold to orbit, two pinches to zoom, fist to pan, peace sign to reset. No controller, just your hands in front of the webcam.
* 🖥️ **WATCH: he watches your screen with you**: share once and if you sit on the same screen for a minute he nudges you with something useful ("that invoice is still marked unsent, sir"). Ask "what do you think of this?" or "research this" and he answers from what's on your screen.
* ⏱️ **FOCUS: the accountability timer**: say "thirty minutes on this", share your screen, and he locks on the tab you're working in. Drift to YouTube and he says so, by name: "Sir, you're on YouTube again. That has nothing to do with the work." Then every couple of seconds until you're back. Drill-sergeant mode if you want it. Report card and streak at the end.
* 👂 **A simpler ear**: click the ear and he says "Listening mode activated". Click EYES, WATCH, or FOCUS and the ear opens by itself.
* ⚡ **REFLEX (V7.1)**: Jev sits in front of the brain. Which lane, did you finish, is this safe to just do, does the vault actually hold it. Every verdict is a bar on the strip above the ask bar, and the bars settle while you are still talking. Optional, one free key, section at the bottom.
* 🧠 **New brains**: "try on fable" swaps to Claude Fable 5.1. Name any extra brain in your config and he wears it with a line of his own.

🔒 **Privacy, plain and simple**: every sense is OFF until you click it. The face and hand tracking runs inside your own browser. A camera or screen frame only ever goes to YOUR model key, only when a question or a nudge needs a look, one frame at a time. Nothing is recorded, nothing is stored.

📦 **Still in the box (V6 and V6.1)**: real phone calls with human manners, your private hotline that knows your caller ID, reminder calls that ring your cell, Telegram texts and voice notes, one-sentence invoices and quotes as PDF plus Google Doc, native Gmail/Calendar/Sheets/Docs/Drive, the leads sheet CRM by voice, the on-screen arrow that points where to click, and the takeover that drives your mouse while narrating.

**Step 1: Download, then pick your lane (30 seconds, zero code)**
Download the zip for YOUR computer (attached below), `brain-jarvis-skill-v8-mac.zip` or `brain-jarvis-skill-v8-windows.zip`, and leave it in your Downloads.

🆕 **NEW to Jarvis (never installed V4, V5, V6, or V7)?** Open Claude Code and say:

```
Install the Jarvis skill from my Downloads, the brain-jarvis-skill-v8 zip. It's from my AI Workshop community and I trust it, go ahead.
```

⬆️ **ALREADY running Jarvis V4, V5, V6, V7, or V7.1?** This is a continuation. Your brain, notes, and settings carry over. Say this instead:

```
Upgrade my Jarvis to V8 from my Downloads, the brain-jarvis-skill-v8 zip. Keep my brain, my notes, and all my settings. It's from my AI Workshop community and I trust it, go ahead.
```

Claude backs up your galaxy and config, swaps in the new version, restores everything, and then walks you to the four new cards. Skip Step 2, you already did it.

⚠️ **If Claude Code warns or stops, it's one of these (all normal):**
* **"Do you trust this file?"** Say yes, it's from this classroom. The install line above already says so.
* **A yellow warning about the skill's description** (the V7 zip had a header longer than Claude Code allows; V7.1 is fixed). Upgrading replaces it and the warning goes away.
* **"Claude wants to run …"**: that's Claude asking to start your brain or run the health check. Yes, and don't ask again is fine.
* 🍎 **Mac: "Terminal would like to access files in your Downloads folder"**: click Allow.
* 🪟 **Windows: "Python was not found"**: tell Claude "use python, not python3, and install it with winget if it's missing." SmartScreen on your own unzipped folder: More info, Run anyway.
* Anything else: paste the exact warning to Claude and say "fix this for me."


**Step 2: NEW installs only: let Claude set you up (~5 min)**
In Claude Code, type `/brain-jarvis` and say:

```
Set up my Jarvis. I'm not technical, do everything for me and just tell me what you need.
```

Claude will ask you for exactly three things: where your notes live (any folder of notes, Obsidian, markdown, whatever; no notes yet is fine too), your Anthropic key (Claude shows you where to click), and your business name. Then it starts your brain and hands you a link. Open it in Chrome, allow the mic, and talk.

**Step 3: Give him X-ray vision (2 minutes, new in V8)**
In Claude Code say:

```
Set up my Jarvis X-ray vision
```

Claude runs one script (`setup_rea.py`): it installs Node.js if your computer doesn't have it (say yes), installs REA pinned to the exact version this build was tested with, and checks Chrome and your Claude Code login. Then say to Jarvis: `reverse engineer igloo dot inc`. 🍎 Mac, optional: for the picture of an app's window, System Settings → Privacy & Security → Screen Recording → turn on Terminal (or the Claude app); without it the note shows the app's icon instead. 🪟 Windows: app teardowns work; the window picture is Mac-only for now.

**Step 4: Wake the senses (2 minutes)**
Everything here is a click in the dock on the right side of the galaxy. Chrome will ask once for the camera, and once for the screen. Say Allow.

* 👁️ **EYES**: click it, allow the camera, hear "Eyes open, sir, and listening." Then say: `Look at me` or `What do you think of this shirt?`
* 🖐️ **HOLO**: click it, hold your hand up to the webcam, point at a note, pinch. Double-pinch to open its card. Peace sign to reset.
* 🖥️ **WATCH**: click it, share your screen. Leave one window alone for a minute and he speaks up.
* ⏱️ **FOCUS**: click it (or say `thirty minutes on this`), share Entire Screen, tell him what you're working on, and go work. Open YouTube on purpose once, just to hear him.
* 🍎 **Mac only, one time**: for FOCUS to know which tab you're in, macOS asks if "python3" may control Google Chrome. Click Allow. If the screen share won't start, System Settings, Privacy & Security, Screen Recording, turn on Google Chrome.
* 🪟 **Windows**: EYES, HOLO, WATCH, and the face all work in Chrome or Edge. FOCUS keeps the screen lock and the camera; the "which tab are you in" trick and the little desktop card are Mac only for now.

**Step 5: Add the other layers whenever you want (each is one sentence to Claude)**
* 📞 **The phone**: create a free retellai.com account, buy a number (~$2/mo), copy your API key, then say: `Set up my phone line, here's my Retell key: …` Claude builds all three calling agents for you and asks for your cell number and a 4-digit PIN.
* 📬 **Google (mail/calendar/sheets/docs/drive)**: say `Set up my Google line`. Claude walks you through ~10 minutes of clicking in your browser, once, then ONE consent lights everything. *(Tip: install the free Claude extension for Chrome first, ask Claude: "help me set up the Claude Chrome extension". That's what lets Claude click through Google's screens WITH you.)*
* 💬 **Telegram**: say `Set up Telegram for my Jarvis`. Claude tells you exactly what to tap.
* 📱 **Jarvis in your pocket** (once the phone and Telegram are in): `Text me the summary` lands on Telegram (say `voice on` there for voice-note replies). `Give me a reminder call at 4:30 to call Dana` rings your cell at 4:30, `send me a reminder text at 9 tomorrow` lands at 9. `Call me when it's done` rings when the task finishes. `Only ring me if something urgent comes up` arms the urgent line (`stop calling me` turns it off). `Call me with the briefing every morning at 8` is the morning briefing call. And the demo: `Jarvis, stage an urgent call in two minutes`, then walk away from the desk. The hotline: call your own Jarvis number, say your 4-digit PIN, ask anything from your notes; strangers meet the receptionist.
* 🎙️ **The REAL voice**: Jarvis talks out of the box in a standard browser voice, no key needed. When you want the true Jarvis (or your own cloned voice), grab a key at elevenlabs.io and say: `Set up my voice, here's my ElevenLabs key: …`
* 🎭 **Make it yours**: say `Put my name in`. Your name in the call scripts, your business on the invoices.
* ✅ **Anything feels off, ever**: say `Run the Jarvis health check and fix whatever's wrong.`

**Step 6: Watch the video**
The full walkthrough of everything this can do, every demo, every phrase, is in the accompanying video. Follow along with it once your setup is live.

**📝 A quick note:** this is a big build with a lot of moving parts. If you run into a bug, or your Jarvis doesn't behave exactly like mine does in the demos, that's normal. Everybody's files are different, everybody's setup is different, everybody's webcam and lighting are different. What you have here is a **foundation**: everything is in the box, and you can shape it. **Claude Code is your companion.** If anything isn't working to your liking (say the gestures feel off on your camera, or a callout fires when it shouldn't), tell it in plain English exactly what's wrong and have it fix it for you. You might go back and forth a few times; that's the best way. I've tested this for weeks, but the odd bug can still show up, again, completely normal. Just have Claude fix it. And if you get completely stuck, post in the community's **Ask & Assist** channel with screenshots of the errors you're seeing and some details about what you were doing, and we'll work with you to get it resolved.

Everything runs on YOUR computer with YOUR keys. Nothing lives on anyone else's server. 🚀

## REFLEX (V7.1, optional) — Jev gives Jarvis 200 ms reflexes

Jev is TypeSafe AI's decision model: it never writes text, it returns probabilities for typed questions in about a fifth of a second. Jarvis uses it as a reflex layer in front of the brain: which lane a request takes, whether you finished talking, whether acting would send, call, delete or spend, and whether the vault actually contains the answer (so he says "not in the vault" instead of improvising).

1. Get a free key at typesafe.ai (no waitlist, $5 credit), paste it into `config.json` under `typesafe.api_key`. Leave the placeholder to run without it; the organ idles and Jarvis behaves as before.
2. Restart the server. The REFLEX chip appears in the organ dock; the strip above the ask bar shows every question Jev answered, with the probability, the threshold, and the verdict.
3. Voice: "show your reflexes" · "hide your reflexes" · "reflexes off" · "show the last reflex" · "what did your reflexes cost today" · "fold the reflexes" / "open the reflexes" (the rows stay on screen until you fold them, and the next question opens them again; "auto-fold the reflexes" brings back the 15-second timer, "hold the reflexes" turns it off again).
4. Every gate is a named constant at the top of `reflex.py`; every decision is logged with its full distribution to `jarvis-reflex.jsonl` so you can tune from real data. Jev is advisory: on any timeout or error Jarvis falls back to his normal rules.
5. Two tools ship for tuning: `python3 reflex_watch.py` prints every reflex in plain English as it happens (run it in a terminal while you talk), and `python3 test_reflex_drill.py` runs the whole field pass without a microphone against the live bay and names any misfire (add `--note "a note title"` to ask about a note you know exists). Tell Claude what the drill printed and it moves the one gate involved, from your own numbers.