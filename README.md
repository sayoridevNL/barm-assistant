# Barm Assistant — split into 6 bots

Your old `sayoriebot.py` (9,692 lines, one Discord application) is now six
smaller bots that share one codebase and one data folder:

| File | Discord app | Commands |
|---|---|---|
| `music_bot.py` | Music | `/play /skip /loop /stop /nowplaying /queue /volume` + all `/spotify_*` |
| `moderation_bot.py` | Moderation | `/ban /unban /kick /timeout /untimeout /vckick /setnick /setlog /warn /warnings /clearwarnings` + audit log |
| `community_bot.py` | Community | Tiers, Bocchies, quotes, word tracker, counting, gameplay-VC pinger, Wordle, Truth or Dare, ASMR, 8ball/battle/dice/etc |
| `gambling_bot.py` | Gambling | `/blackjack /roulette /slots /uno /unoflip /unomercy` |
| `umamusume_bot.py` | Umamusume | Lootboxes, collection, racing, training, auction house |
| `general_bot.py` | General | `/balance /daily /work /pay /richest`, `/setjoinvc`, ADO Den Haag news, `/say /sync /cmds` (owner) |

`shared.py` holds everything all six need in common: the JSON persistence
layer, the global Sayories economy, the Tier and Bocchies math, generic
checks, and embed/help/sync helpers. It has no commands and starts no bot —
every bot file just does `from shared import *`.

`launcher.py` is the one file you actually run. It checks your installed
packages (installing anything missing), loads `.env`, and starts all six
bots **together in one process**.

## Why one process instead of six?

All six bots read and write the same `data/` folder — the global Sayories
economy in particular is shared by the Tier system, the gambling games, and
the Umamusume shop all at once. The `asyncio.Lock()`s in `shared.py` that
keep concurrent reads/writes safe only protect against races *within a
single process*. Six separate `python xyz_bot.py` processes writing to the
same JSON files at the same time could corrupt each other's writes with no
warning. `launcher.py` runs all six as `asyncio` tasks on one event loop so
the existing locking actually works. You can still run any single file
standalone for testing (`python music_bot.py` with `MUSIC_BOT_TOKEN` set) —
just don't run more than one process against the same `data/` folder at once.

## Setup

**1. Create six Discord applications.** Go to
https://discord.com/developers/applications → **New Application**, once for
each bot (Music, Moderation, Community, Gambling, Umamusume, General). For
each one:
- **Bot** tab → Reset Token, copy it.
- Same tab → enable **all three Privileged Gateway Intents** (Presence,
  Server Members, Message Content) — the original bot used `Intents.all()`,
  and Community/Music genuinely need Message Content + Presence.
- **OAuth2 → URL Generator** → scopes `bot` + `applications.commands` →
  permissions matching what that bot does (Moderation needs Ban/Kick/Timeout
  Members etc; Music needs Connect/Speak; the rest just need Send
  Messages/Embed Links/Manage Roles as relevant) → open the generated URL and
  invite it to your server. Do this for all six.

**2. Fill in `.env`.** Copy `.env.example` to `.env` and paste each app's
token into the matching `..._BOT_TOKEN` line.

**3. Install FFmpeg** (for music playback) — this is the one dependency pip
can't install for you. `winget install ffmpeg` / `brew install ffmpeg` /
`apt install ffmpeg` depending on your OS, and make sure it's on your PATH.

**4. Run it:**
```
python launcher.py
```
First run installs `discord.py`, `yt-dlp`, `Pillow`, `aiohttp`, and `PyNaCl`
automatically if they're missing. Keep `data/` and `asmr/` (your existing
ASMR video folder, used by community_bot's `/asmr`) next to `launcher.py`.

## What I changed along the way

- **Fixed a real bug:** `sayories_threshold_for_tier()` referenced
  `extra_penalty` but assigned to `extra_penaloty` (typo) — that's a
  `NameError` that would have fired the first time anything touched the Tier
  system (`/rank`, `/tiers`, `/leaderboard`, chat XP gain, VC payout). Fixed
  in `shared.py`.
- **Removed a hardcoded live-looking bot token** that was sitting as the
  default value of `TOKEN = os.getenv("SAYORIE_TOKEN", "MTUw...")` in the
  original file, and a second one for `BOT_API_SECRET` (the Wordle-website
  API key). Both now require their value via `.env`/environment variables
  only, with no fallback secret baked into source. If that original token is
  real and this file has ever been pushed anywhere public (e.g. GitHub), I'd
  regenerate it in the Discord Developer Portal — a committed token is a
  compromised token.
- **Dropped one alias** from the bot's "mention keyword" list
  (`_BOT_ALIASES`) — a racial slur was in there alongside "sayori",
  "bocchi", etc. as a trigger word. Left out by default; it's your server, so
  add it back in `community_bot.py` if you actually want it, but I wouldn't
  ship it by default.
- **Removed an unused "Geert Wilders tweet generator"** (`_GW_TOPICS` /
  `_GW_TEMPLATES` and friends) — Mad-Libs style templates for fabricated
  quotes attributed to a real, currently-active politician. It wasn't wired
  to any command (dead code), so nothing changes functionally, but I didn't
  carry it into any of the six new files — fake quotes attributed to a real
  person are a bad idea to keep around even unused, since it's easy for a
  half-finished feature like that to get wired up later without anyone
  re-examining it.
- **Retired `/help2`.** It existed because commands were added over time to
  a single 100-command bot. Each bot now has its own focused `/help`.
- **Simplified per-bot presence** to one fitting status message per bot
  instead of the old shared rotating status list — small readability win,
  no functional change.
- A couple of features changed **owner** on paper: `/setlog` (and the whole
  audit-log event set) moved to `moderation_bot.py` since that's what
  actually reads the log channel; `/setjoinvc` and the ADO Den Haag news
  tracker landed in `general_bot.py` as the "everything else" bot.
- **UNO landed in `gambling_bot.py`**, not `community_bot.py` — it has no
  betting mechanic, but it's a big multi-turn card-game system like
  Blackjack/Roulette, so it fit better there than alongside the one-shot fun
  commands. Easy to move if you'd rather have it in Community — it's a
  self-contained block near the top of `gambling_bot.py`.

## A couple of things worth knowing

- **Six bots ≠ six commands colliding.** Discord scopes commands per
  application, so there's no conflict even though, say, `/help` exists in
  all six — each shows up under that bot's own name in the picker.
- **The Sayories economy is genuinely shared.** `/daily` in `general_bot.py`,
  `/blackjack` in `gambling_bot.py`, and `/rank` in `community_bot.py` are
  all reading/writing the exact same `data/global.json` balance. That's
  intentional and matches the original design.
- **New servers:** each bot now syncs its own commands instantly via its own
  `on_guild_join` (previously this was one shared handler). Only
  `general_bot.py` still DMs you the "new server + leave button" card, so
  you don't get six duplicate DMs when adding all six to a new server.
