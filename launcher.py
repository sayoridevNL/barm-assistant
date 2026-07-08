"""
launcher.py — Entry point for running an individual Barm assistant bot.
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
import json
import discord
from discord.ext import tasks
import shared  # noqa: F401 - imports shared .env loader before token lookup

BOTS = {
    "music_bot": "MUSIC_BOT_TOKEN",
    "moderation_bot": "MODERATION_BOT_TOKEN",
    "community_bot": "COMMUNITY_BOT_TOKEN",
    "gambling_bot": "GAMBLING_BOT_TOKEN",
    "umamusume_bot": "UMAMUSUME_BOT_TOKEN",
    "general_bot": "GENERAL_BOT_TOKEN",
}

async def main(bot_name):
    if bot_name not in BOTS:
        print(f"❌ Unknown bot name: {bot_name}")
        return

    env_var = BOTS[bot_name]
    token = os.getenv(env_var)
    
    if not token:
        print(f"⚠️  Skipping {bot_name} — {env_var} is not set (check your .env).")
        return
        
    token = token.strip()
    
    module = importlib.import_module(bot_name)
    bot = module.bot
    
    # Inject background task for presence checking
    @tasks.loop(seconds=15)
    async def update_presence_loop():
        try:
            if os.path.exists('presence.json'):
                with open('presence.json', 'r', encoding='utf-8') as f:
                    presences = json.load(f)
                new_presence = presences.get(bot_name, "").strip()
                
                # Check current presence
                current_presence = ""
                if bot.guilds and bot.guilds[0].me.activity:
                    current_presence = bot.guilds[0].me.activity.name
                    
                if new_presence and current_presence != new_presence:
                    await bot.change_presence(activity=discord.Game(name=new_presence))
        except Exception as e:
            print(f"Presence update error for {bot_name}: {e}")

    @update_presence_loop.before_loop
    async def before_presence_loop():
        await bot.wait_until_ready()

    update_presence_loop.start()

    try:
        print(f"🚀 Starting {bot_name}...")
        await bot.start(token)
    except Exception as e:
        print(f"❌ {bot_name} crashed: {e.__class__.__name__}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python launcher.py <bot_name>")
        sys.exit(1)
        
    target_bot = sys.argv[1]
    
    try:
        asyncio.run(main(target_bot))
    except KeyboardInterrupt:
        print(f"\n👋 Shutting down {target_bot}.")
