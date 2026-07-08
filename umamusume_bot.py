from __future__ import annotations
import os
import random
import time
import uuid as _uuid
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from shared import *
from shared import _global_lock, _load_global, _save_global
from theme import EmbedBuilder, Palette
from ui_kit import Paginator, ask_confirm, install_error_handler

_RARITY_WEIGHTS = {"Legendary": 0.35, "SSR": 3.5, "SR": 22, "R": 74}
_RARITY_COLORS  = {"Legendary": 0xFFD700, "SSR": 0xFF4500, "SR": 0x9B59B6, "R": 0x3498DB}
_RARITY_EMOJI   = {"Legendary": "✨👑✨", "SSR": "🔶", "SR": "🔷", "R": "⬜"}
_UMA_GLOBAL_SECTION = "uma_inventory"

_UMA_POOL = [
    ("Haru Urara", "Legendary", 60, 90, 40, 50, 95, "https://umamusu.wiki/w/thumb.php?f=Haru_Urara_%28Icon%29.png&width=140"),
    ("Special Week", "SSR", 85, 80, 88, 82, 80, "https://umamusu.wiki/w/thumb.php?f=Special_Week_%28Icon%29.png&width=140"),
    ("Silence Suzuka", "SSR", 92, 75, 82, 78, 85, "https://umamusu.wiki/w/thumb.php?f=Silence_Suzuka_%28Icon%29.png&width=140"),
]

def _uma_power_score(uma: dict) -> int:
    return int(uma.get("speed", 0) * 0.35 + uma.get("stamina", 0) * 0.25 + uma.get("power", 0) * 0.20 + uma.get("smartness", 70) * 0.10 + uma.get("guts", 70) * 0.10)

def _stat_bar(val: int, max_val: int = 150) -> str:
    filled = min(10, int((val / max_val) * 10))
    return "█" * filled + "░" * (10 - filled) + f" {val}"

async def _uma_get_inventory(user_id: int) -> dict:
    inv = await global_get_section(_UMA_GLOBAL_SECTION)
    return inv.get(str(user_id), {})

async def _uma_save_inventory(user_id: int, data: dict):
    async with _global_lock:
        d = _load_global()
        d.setdefault(_UMA_GLOBAL_SECTION, {})[str(user_id)] = data
        _save_global(d)

_LOOTBOX_TIERS = {
    "basic": {"label": "🎁 Basic Box", "emoji": "🎁", "cost": 2_000, "color": 0x3498DB, "weights": {"Legendary": 0.10, "SSR": 1.5, "SR": 13.4, "R": 85.0}, "flavor": "A standard capsule fresh off the track."},
    "premium": {"label": "💎 Premium Box", "emoji": "💎", "cost": 8_000, "color": 0x9B59B6, "weights": {"Legendary": 0.50, "SSR": 5.5, "SR": 29.0, "R": 65.0}, "flavor": "A premium capsule — slightly better SR/SSR odds."},
    "elite": {"label": "🏆 Elite Box", "emoji": "🏆", "cost": 25_000, "color": 0xFF4500, "weights": {"Legendary": 1.5, "SSR": 15.5, "SR": 53.0, "R": 30.0}, "flavor": "Elite-grade capsule — no guaranteed SSR, but R is rare."},
    "legend": {"label": "👑 Legend Box", "emoji": "👑", "cost": 75_000, "color": 0xFFD700, "weights": {"Legendary": 4.0, "SSR": 46.0, "SR": 50.0, "R": 0.0}, "flavor": "Legend-tier capsule — no R rarity, meaningful SSR rate."},
    "divine": {"label": "✨ Divine Box", "emoji": "✨", "cost": 200_000, "color": 0xFFFFFF, "weights": {"Legendary": 10.0, "SSR": 90.0, "SR": 0.0, "R": 0.0}, "flavor": "Divine capsule — SSR guaranteed, 10% shot at Legendary."},
}

def _uma_roll(weights_override: dict | None = None) -> dict:
    w = weights_override or _RARITY_WEIGHTS
    valid_rarities = {r for r, wt in w.items() if wt > 0}
    filtered = [u for u in _UMA_POOL if u[1] in valid_rarities]
    weights = [w[u[1]] for u in filtered]
    picked = random.choices(filtered, weights=weights, k=1)[0]
    return {"name": picked[0], "rarity": picked[1], "speed": picked[2], "stamina": picked[3], "power": picked[4], "smartness": picked[5], "guts": picked[6], "image": picked[7], "wins": 0, "races": 0, "id": str(_uuid.uuid4())[:8]}

def _uma_image(uma: dict) -> str:
    img = uma.get("image", "")
    if img:
        sep = "&" if "?" in img else "?"
        img = f"{img}{sep}_cb={int(time.time())}"
    return img

class UmamusumeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="§unused-uma§", intents=intents, help_command=None)

    async def on_ready(self):
        print("🔄 Syncing umamusume bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("umamusume", self)
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["umamusume"]["status"]))

bot = UmamusumeBot()
tree = bot.tree
install_error_handler(tree)

@tree.command(name="lootbox_shop", description="🎁 View Umamusume loot box prices and odds")
async def lootbox_shop(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    embed = (EmbedBuilder(color=Palette.PRIMARY)
        .title("🎁 Umamusume Loot Box Shop")
        .description("Pick a box with `/lootbox <tier>`. Higher tiers cost more and improve rarity odds."))
    for key, tier in _LOOTBOX_TIERS.items():
        odds = " • ".join(f"{rarity} `{weight:g}%`" for rarity, weight in tier["weights"].items() if weight > 0)
        embed.field(tier["label"], f"Cost: **{tier['cost']:,} Sayories**\n{tier['flavor']}\n{odds}", inline=False)
    await interaction.response.send_message(embed=embed.branded("Umamusume").build())

@tree.command(name="lootbox", description="🎁 Open an Umamusume loot box!")
@app_commands.describe(tier="Which box to open — higher tier = better odds & higher cost")
@app_commands.choices(tier=[app_commands.Choice(name="🎁 Basic     —   2,000 Sayories", value="basic"), app_commands.Choice(name="💎 Premium  —   8,000 Sayories", value="premium"), app_commands.Choice(name="🏆 Elite    —  25,000 Sayories", value="elite"), app_commands.Choice(name="👑 Legend   —  75,000 Sayories", value="legend"), app_commands.Choice(name="✨ Divine   — 200,000 Sayories", value="divine")])
async def lootbox(interaction: discord.Interaction, tier: str = "basic"):
    if not await dm_check(interaction): return
    t = _LOOTBOX_TIERS[tier]; cost = t["cost"]
    bal = await g_eco_get(interaction.user.id)
    if bal < cost: return await interaction.response.send_message(f"❌ You need **{cost:,} Sayories** to open a **{t['label']}** (you have {bal:,}).", ephemeral=True)
    await g_eco_add(interaction.user.id, -cost)

    embed = (EmbedBuilder(color=t["color"]).title("🏟️ STARTING GATE LOCKED").description(f"```\n┌────────────────────────────────────────┐\n│  {t['emoji']} OPENING: {t['label']:<26} │\n│                                        │\n│       🎌 CONNECTING TO TRACK...        │\n│                                        │\n└────────────────────────────────────────┘\n```\n✨ *Awakening the spirit of a hidden Uma...*").build())
    await interaction.response.send_message(embed=embed)
    await asyncio.sleep(1.5)

    uma = _uma_roll(weights_override=t["weights"])
    inv = await _uma_get_inventory(interaction.user.id)
    inv.setdefault("umas", []).append(uma)
    await _uma_save_inventory(interaction.user.id, inv)

    color = _RARITY_COLORS[uma["rarity"]]; remoji = _RARITY_EMOJI[uma["rarity"]]
    is_leg = uma["rarity"] == "Legendary"

    leg_text = '## 🎊 **LEGENDARY PULL!!!** 🎊\n' if is_leg else ''
    reveal_embed = (EmbedBuilder(color=color)
        .title(f"{remoji} UNLOCKED: {uma['name']}  [{uma['rarity']}]")
        .description(f"{leg_text}\n>>> *A new Uma has joined your team!*")
        .fields(("⚡ Speed", f"`{uma['speed']}`"), ("❤️ Stamina", f"`{uma['stamina']}`"), ("💪 Power", f"`{uma['power']}`"), ("🧠 Smartness", f"`{uma.get('smartness', 70)}`"), ("🔥 Guts", f"`{uma.get('guts', 70)}`"), ("🆔 Uma ID", f"`{uma['id']}`"))
        .field(f"{t['emoji']} Box Used", f"**{t['label']}** — {cost:,} Sayories", inline=False)
        .build())
    img = _uma_image(uma)
    if img: reveal_embed.set_image(url=img)
    reveal_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    reveal_embed.set_footer(text=f"Cost: {cost:,} Sayories • Remaining: {bal - cost:,} 🪙")
    
    await interaction.edit_original_response(content="## 🌸 THE GATES BURST OPEN... A NEW UMA APPEARS! 🌸", embed=reveal_embed)

@tree.command(name="uma_inventory", description="🐴 View your Umamusume collection (paginated with images)")
async def uma_inventory(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    inv = await _uma_get_inventory(interaction.user.id)
    umas = inv.get("umas", [])
    if not umas: return await interaction.response.send_message("🎁 You have no Umamusume! Open a `/lootbox` to get started.", ephemeral=True)

    rarity_order = {"Legendary": 0, "SSR": 1, "SR": 2, "R": 3}
    umas_sorted = sorted(umas, key=lambda u: (rarity_order.get(u.get("rarity", "R"), 4), -_uma_power_score(u)))

    pages = []
    for u in umas_sorted:
        u.setdefault("smartness", 70); u.setdefault("guts", 70)
        color = _RARITY_COLORS[u["rarity"]]; remoji = _RARITY_EMOJI[u["rarity"]]
        embed = (EmbedBuilder(color=color).title(f"{remoji} {u['name']} [{u['rarity']}]").description(f"🆔 ID: `{u['id']}` | 🏆 Race Record: **{u['wins']}W / {u['races']}R**\n⚡ **Overall Power Score:** `{_uma_power_score(u)}`").fields(("⚡ Speed", f"`{_stat_bar(u['speed'])}`"), ("❤️ Stamina", f"`{_stat_bar(u['stamina'])}`"), ("💪 Power", f"`{_stat_bar(u['power'])}`"), ("🧠 Smartness", f"`{_stat_bar(u['smartness'])}`"), ("🔥 Guts", f"`{_stat_bar(u['guts'])}`")).build())
        img = _uma_image(u)
        if img: embed.set_image(url=img)
        pages.append(embed)

    view = Paginator(pages, author_id=interaction.user.id)
    await interaction.response.send_message(embed=pages[0], view=view)

@tree.command(name="uma_view", description="🐴 View a specific Uma by ID")
@app_commands.describe(uma_id="The Uma ID from /uma_inventory")
async def uma_view(interaction: discord.Interaction, uma_id: str):
    if not await dm_check(interaction): return
    inv = await _uma_get_inventory(interaction.user.id)
    uma = next((u for u in inv.get("umas", []) if u.get("id") == uma_id), None)
    if not uma:
        await interaction.response.send_message("❌ Uma not found.", ephemeral=True)
        return
    uma.setdefault("smartness", 70)
    uma.setdefault("guts", 70)
    color = _RARITY_COLORS.get(uma.get("rarity", "R"), Palette.PRIMARY)
    remoji = _RARITY_EMOJI.get(uma.get("rarity", "R"), "🐴")
    embed = (EmbedBuilder(color=color)
        .title(f"{remoji} {uma['name']} [{uma['rarity']}]")
        .description(f"🆔 ID: `{uma['id']}` | 🏆 Race Record: **{uma['wins']}W / {uma['races']}R**\n⚡ **Overall Power Score:** `{_uma_power_score(uma)}`")
        .fields(("⚡ Speed", f"`{_stat_bar(uma['speed'])}`"), ("❤️ Stamina", f"`{_stat_bar(uma['stamina'])}`"), ("💪 Power", f"`{_stat_bar(uma['power'])}`"), ("🧠 Smartness", f"`{_stat_bar(uma['smartness'])}`"), ("🔥 Guts", f"`{_stat_bar(uma['guts'])}`"))
        .branded("Umamusume").build())
    img = _uma_image(uma)
    if img: embed.set_image(url=img)
    await interaction.response.send_message(embed=embed)

@tree.command(name="uma_fastsell", description="⚡ Instantly sell your Uma for the minimum price")
@app_commands.describe(uma_id="The Uma ID to sell (from /uma_inventory)")
async def uma_fastsell(interaction: discord.Interaction, uma_id: str):
    if not await dm_check(interaction): return
    inv = await _uma_get_inventory(interaction.user.id)
    uma = next((u for u in inv.get("umas", []) if u["id"] == uma_id), None)
    if not uma: return await interaction.response.send_message("❌ Uma not found.", ephemeral=True)

    base = {"Legendary": 7000, "SSR": 2000, "SR": 700, "R": 235}.get(uma.get("rarity", "R"), 80)
    total = (uma.get("speed", 0) + uma.get("stamina", 0) + uma.get("power", 0) + uma.get("smartness", 70) + uma.get("guts", 70))
    sell_price = base + (total // 5)

    confirmed = await ask_confirm(interaction, EmbedBuilder(color=Palette.WARNING).title("⚡ Fast Sell Uma").description(f"Are you sure you want to sell **{uma['name']}** [{uma['rarity']}]?\n\n💰 You'll receive: **{sell_price:,} Sayories** (minimum price)\n⚡ **Pwr Score:** `{_uma_power_score(uma)}`\n\n⚠️ **This cannot be undone!**").image(_uma_image(uma)).build(), confirm_label=f"Sell for {sell_price:,}")
    if not confirmed: return

    inv["umas"] = [u for u in inv["umas"] if u["id"] != uma_id]
    await _uma_save_inventory(interaction.user.id, inv)
    new_bal = await g_eco_add(interaction.user.id, sell_price)
    
    embed = (EmbedBuilder(color=Palette.SUCCESS).title("⚡ Uma Sold!").description(f"**{uma['name']}** [{uma['rarity']}] has been sold!\n\n💰 You received: **{sell_price:,} Sayories**\n💵 New balance: **{new_bal:,} Sayories**").thumbnail(interaction.user.display_avatar.url).footer("Tip: /lootbox opens another box when you're ready • Barm assistant 🐴").build())
    await interaction.followup.send(embed=embed)

@tree.command(name="help", description="Show all Umamusume bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("umamusume", "Collect and manage Umamusume with the shared Sayories economy.", {"🎁 Gacha": ["`/lootbox_shop` — prices and odds", "`/lootbox <tier>` — open a box"], "🐴 Collection": ["`/uma_inventory` — paginated collection", "`/uma_view <uma_id>` — inspect one Uma", "`/uma_fastsell <uma_id>` — sell one Uma instantly"]})
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("UMAMUSUME_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the UMAMUSUME_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
