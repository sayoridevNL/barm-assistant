"""
launcher.py — Single entry point for all six Barm assistant bots.
"""
from __future__ import annotations
import importlib
import importlib.util
import subprocess
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

REQUIRED_PACKAGES = [
    ("discord", "discord.py"),
    ("yt_dlp", "yt-dlp"),
    ("PIL", "Pillow"),
    ("aiohttp", "aiohttp"),
    ("nacl", "PyNaCl"),
]

def ensure_packages_installed():
    missing = [pip_name for module_name, pip_name in REQUIRED_PACKAGES if importlib.util.find_spec(module_name) is None]
    if not missing: return
    print(f"📦 Installing missing packages: {', '.join(missing)}")
    subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", *missing], check=True)
    importlib.invalidate_caches()
    print("✅ Packages installed.\n")

ensure_packages_installed()

import asyncio
import os
import shared  # noqa: F401 - imports shared .env loader before token lookup

BOTS = [
    ("MUSIC_BOT_TOKEN",      "music_bot"),
    ("MODERATION_BOT_TOKEN", "moderation_bot"),
    ("COMMUNITY_BOT_TOKEN",  "community_bot"),
    ("GAMBLING_BOT_TOKEN",   "gambling_bot"),
    ("UMAMUSUME_BOT_TOKEN",  "umamusume_bot"),
    ("GENERAL_BOT_TOKEN",    "general_bot"),
]

async def main():
    tasks, started = [], []
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("⚠️  FFmpeg not found on PATH — /play (music_bot) needs it installed separately.\n")

    for env_var, module_name in BOTS:
        token = os.getenv(env_var)
        if not token:
            print(f"⚠️  Skipping {module_name} — {env_var} is not set (check your .env).")
            continue
        module = importlib.import_module(module_name)
        
        async def run_bot(bot, t, n):
            try:
                await bot.start(t)
            except Exception as e:
                print(f"❌ {n} crashed: {e.__class__.__name__}: {e}")
                
        tasks.append(asyncio.create_task(run_bot(module.bot, token, module_name), name=module_name))
        started.append(module_name)

    if not tasks:
        print("❌ No bot tokens found. Copy .env.example to .env, fill in your tokens, and try again.")
        return

    print(f"🚀 Starting {len(tasks)}/6 bot(s): {', '.join(started)}\n")

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for task, result in zip(tasks, results):
        if isinstance(result, Exception):
            print(f"❌ {task.get_name()} crashed: {result}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Shutting down all bots.")
