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
from theme import EmbedBuilder, Palette
from ui_kit import Paginator, ask_confirm, install_error_handler

def _wiki_icon(name: str) -> str:
    slug = name.replace(" ", "_").replace("'", "%27")
    return f"https://umamusu.wiki/w/thumb.php?f={slug}_%28Icon%29.png&width=140"

# ─────────────────────────────  Uma (Trainee) gacha  ─────────────────────────────
# Real game note: Trainees are rated in Stars (1-3), NOT R/SR/SSR — that scale is
# reserved for Support Cards below. Duplicates raise a Trainee's Star Grade further
# (up to 5) via Star Pieces in the real game; we skip that extra layer here and just
# track ownership + a flat power score.

_UMA_RARITY_WEIGHTS = {"3-Star": 3, "2-Star": 18, "1-Star": 79}
_UMA_RARITY_COLORS  = {"3-Star": 0xFFD700, "2-Star": 0x9B59B6, "1-Star": 0x3498DB}
_UMA_RARITY_EMOJI   = {"3-Star": "⭐⭐⭐", "2-Star": "⭐⭐", "1-Star": "⭐"}
_UMA_GLOBAL_SECTION = "uma_inventory"

# name, rarity, speed, stamina, power, wit, guts, image
_UMA_POOL = [
    ("Special Week", "3-Star", 95, 100, 90, 90, 85, _wiki_icon("Special_Week")),
    ("Silence Suzuka", "3-Star", 115, 70, 75, 75, 80, _wiki_icon("Silence_Suzuka")),
    ("Tokai Teio", "3-Star", 100, 85, 100, 80, 90, _wiki_icon("Tokai_Teio")),
    ("Mejiro McQueen", "3-Star", 80, 115, 75, 90, 85, _wiki_icon("Mejiro_McQueen")),
    ("Gold Ship", "3-Star", 85, 110, 90, 70, 100, _wiki_icon("Gold_Ship")),
    ("Vodka", "3-Star", 100, 75, 105, 80, 85, _wiki_icon("Vodka")),
    ("Daiwa Scarlet", "3-Star", 105, 80, 95, 75, 90, _wiki_icon("Daiwa_Scarlet")),
    ("Grass Wonder", "3-Star", 90, 95, 85, 80, 100, _wiki_icon("Grass_Wonder")),
    ("El Condor Pasa", "3-Star", 90, 80, 110, 85, 85, _wiki_icon("El_Condor_Pasa")),
    ("Oguri Cap", "3-Star", 100, 100, 105, 85, 105, _wiki_icon("Oguri_Cap")),
    ("Symboli Rudolf", "3-Star", 90, 90, 85, 100, 95, _wiki_icon("Symboli_Rudolf")),
    ("Rice Shower", "3-Star", 80, 105, 75, 80, 90, _wiki_icon("Rice_Shower")),
    ("Maruzensky", "3-Star", 120, 70, 80, 75, 75, _wiki_icon("Maruzensky")),
    ("Kitasan Black", "3-Star", 105, 95, 90, 85, 90, _wiki_icon("Kitasan_Black")),
    ("Agnes Tachyon", "2-Star", 85, 75, 70, 110, 70, _wiki_icon("Agnes_Tachyon")),
    ("Air Groove", "2-Star", 90, 85, 90, 85, 95, _wiki_icon("Air_Groove")),
    ("T.M. Opera O", "2-Star", 85, 95, 95, 80, 90, _wiki_icon("T.M._Opera_O")),
    ("Seiun Sky", "2-Star", 80, 90, 80, 75, 85, _wiki_icon("Seiun_Sky")),
    ("King Halo", "2-Star", 85, 85, 90, 75, 90, _wiki_icon("King_Halo")),
    ("Nice Nature", "1-Star", 75, 80, 75, 90, 80, _wiki_icon("Nice_Nature")),
    ("Haru Urara", "1-Star", 40, 55, 45, 60, 90, _wiki_icon("Haru_Urara")),
    # Special/seasonal versions — in the real game every alternate costume is treated
    # as a fully distinct Trainee with its own pull entry, own stats, own art.
    ("Haru Urara (New Year)", "3-Star", 55, 65, 55, 65, 110, _wiki_icon("Haru_Urara")),
    ("Maruzensky (Summer)", "3-Star", 115, 75, 85, 80, 80, _wiki_icon("Maruzensky")),
]

def _uma_power_score(uma: dict) -> int:
    return int(uma.get("speed", 0) * 0.35 + uma.get("stamina", 0) * 0.25 + uma.get("power", 0) * 0.20 + uma.get("wit", 70) * 0.10 + uma.get("guts", 70) * 0.10)

def _stat_bar(val: int, max_val: int = 150) -> str:
    filled = min(10, int((val / max_val) * 10))
    return "█" * filled + "░" * (10 - filled) + f" {val}"

async def _uma_get_inventory(user_id: int) -> dict:
    inv = await global_get_section(_UMA_GLOBAL_SECTION)
    return inv.get(str(user_id), {})

async def _uma_save_inventory(user_id: int, data: dict):
    inv_global = await global_get_section(_UMA_GLOBAL_SECTION)
    inv_global[str(user_id)] = data
    await global_save_section(_UMA_GLOBAL_SECTION, inv_global)

_UMA_LOOTBOX_TIERS = {
    "basic":   {"label": "🎁 Basic Box",   "emoji": "🎁", "cost": 2_000,   "color": 0x3498DB, "weights": {"3-Star": 3,  "2-Star": 18, "1-Star": 79}, "flavor": "A standard capsule fresh off the track — same odds as the real Pretty Derby Scout."},
    "premium": {"label": "💎 Premium Box", "emoji": "💎", "cost": 8_000,   "color": 0x9B59B6, "weights": {"3-Star": 10, "2-Star": 30, "1-Star": 60}, "flavor": "A premium capsule — noticeably better 2★/3★ odds."},
    "elite":   {"label": "🏆 Elite Box",   "emoji": "🏆", "cost": 25_000,  "color": 0xFF4500, "weights": {"3-Star": 25, "2-Star": 40, "1-Star": 35}, "flavor": "Elite-grade capsule — 3★ pulls start getting common."},
    "legend":  {"label": "👑 Legend Box",  "emoji": "👑", "cost": 75_000,  "color": 0xFFD700, "weights": {"3-Star": 50, "2-Star": 40, "1-Star": 10}, "flavor": "Legend-tier capsule — mostly 2★/3★ trainees."},
    "divine":  {"label": "✨ Divine Box",  "emoji": "✨", "cost": 200_000, "color": 0xFFFFFF, "weights": {"3-Star": 80, "2-Star": 20, "1-Star": 0},  "flavor": "Divine capsule — guaranteed 2★ or better, heavy odds on 3★."},
}

def _uma_roll(weights_override: dict | None = None) -> dict:
    w = weights_override or _UMA_RARITY_WEIGHTS
    valid_rarities = {r for r, wt in w.items() if wt > 0}
    filtered = [u for u in _UMA_POOL if u[1] in valid_rarities]
    weights = [w[u[1]] for u in filtered]
    picked = random.choices(filtered, weights=weights, k=1)[0]
    return {"name": picked[0], "rarity": picked[1], "speed": picked[2], "stamina": picked[3], "power": picked[4], "wit": picked[5], "guts": picked[6], "image": picked[7], "wins": 0, "races": 0, "id": str(_uuid.uuid4())[:8]}

def _uma_image(uma: dict) -> str:
    img = uma.get("image", "")
    if img:
        sep = "&" if "?" in img else "?"
        img = f"{img}{sep}_cb={int(time.time())}"
    return img

# ─────────────────────────────  Support Card gacha  ─────────────────────────────
# Real game note: Support Cards are a completely separate gacha pool from Trainees
# (their own banner, own pity), using real R / SR / SSR rarity and one of six real
# specialties (Speed, Stamina, Power, Guts, Wit, Friend). Real cards grant several
# distinct training bonuses (friendship %, training %, hint level, etc.) — this bot
# collapses those into a single "Support Bonus" number to keep the loot box simple.

_SUPPORT_RARITY_WEIGHTS = {"SSR": 3, "SR": 18, "R": 79}
_SUPPORT_RARITY_COLORS  = {"SSR": 0xFF4500, "SR": 0x9B59B6, "R": 0x3498DB}
_SUPPORT_RARITY_EMOJI   = {"SSR": "🔶", "SR": "🔷", "R": "⬜"}
_SUPPORT_TYPE_EMOJI     = {"Speed": "⚡", "Stamina": "❤️", "Power": "💪", "Guts": "🔥", "Wit": "🧠", "Friend": "🤝"}
_SUPPORT_GLOBAL_SECTION = "uma_support_inventory"

# name, type, rarity, bonus, image, flavor
_SUPPORT_POOL = [
    ("Special Week", "Guts", "R", 25, _wiki_icon("Special_Week"), "A steady training partner who keeps morale up."),
    ("Silence Suzuka", "Speed", "R", 25, _wiki_icon("Silence_Suzuka"), "Front-runner instincts, straight off the track."),
    ("Tokai Teio", "Speed", "R", 22, _wiki_icon("Tokai_Teio"), "Sharp acceleration drills."),
    ("Oguri Cap", "Power", "R", 24, _wiki_icon("Oguri_Cap"), "Grey-haired grit, built for the long haul."),
    ("Gold Ship", "Stamina", "R", 20, _wiki_icon("Gold_Ship"), "Unorthodox methods, surprisingly effective."),
    ("Symboli Rudolf", "Wit", "R", 23, _wiki_icon("Symboli_Rudolf"), "The Emperor's calm, calculated approach."),
    ("Super Creek", "Stamina", "R", 26, _wiki_icon("Super_Creek"), "A shooting star of stamina know-how."),
    ("Haru Urara", "Guts", "R", 18, _wiki_icon("Haru_Urara"), "Never wins, never quits — pure heart."),
    ("Tazuna Hayakawa", "Friend", "R", 20, _wiki_icon("Tazuna_Hayakawa"), "Keeps the whole team's spirits up."),
    ("Nice Nature", "Wit", "SR", 48, _wiki_icon("Nice_Nature"), "Consistently, reliably, third place."),
    ("Seeking the Pearl", "Stamina", "SR", 50, _wiki_icon("Seeking_the_Pearl"), "Patient, methodical stamina building."),
    ("Mejiro Ryan", "Stamina", "SR", 46, _wiki_icon("Mejiro_Ryan"), "Steady, dependable training rhythm."),
    ("Sakura Bakushin O", "Power", "SR", 52, _wiki_icon("Sakura_Bakushin_O"), "Explosive sprint-focused drills."),
    ("Vodka", "Guts", "SR", 49, _wiki_icon("Vodka"), "Cool confidence under pressure."),
    ("Fine Motion", "Stamina", "SR", 51, _wiki_icon("Fine_Motion"), "Elegant, disciplined stamina work."),
    ("Special Week", "Guts", "SSR", 80, _wiki_icon("Special_Week"), "Mood +60%, Training Effectiveness +10%."),
    ("Silence Suzuka", "Speed", "SSR", 85, _wiki_icon("Silence_Suzuka"), "Friendship +35%, Initial Speed +30%."),
    ("Tokai Teio", "Speed", "SSR", 78, _wiki_icon("Tokai_Teio"), "Mood +60%, Race Bonus +10%, Fan Bonus +15%."),
    ("Kitasan Black", "Speed", "SSR", 90, _wiki_icon("Kitasan_Black"), "The gold standard of Speed cards."),
    ("El Condor Pasa", "Power", "SSR", 82, _wiki_icon("El_Condor_Pasa"), "Dirt Master, Mile King skill access."),
    ("Mr. C.B.", "Wit", "SSR", 79, _wiki_icon("Mr._C.B."), "Sharp, versatile Wit training."),
]

async def _support_get_inventory(user_id: int) -> dict:
    inv = await global_get_section(_SUPPORT_GLOBAL_SECTION)
    return inv.get(str(user_id), {})

async def _support_save_inventory(user_id: int, data: dict):
    inv_global = await global_get_section(_SUPPORT_GLOBAL_SECTION)
    inv_global[str(user_id)] = data
    await global_save_section(_SUPPORT_GLOBAL_SECTION, inv_global)

_SUPPORT_LOOTBOX_TIERS = {
    "basic":   {"label": "🎁 Basic Support Box",   "emoji": "🎁", "cost": 1_500,   "color": 0x3498DB, "weights": {"SSR": 3,  "SR": 18, "R": 79}, "flavor": "Same odds as the real Support Card Scout."},
    "premium": {"label": "💎 Premium Support Box", "emoji": "💎", "cost": 6_000,   "color": 0x9B59B6, "weights": {"SSR": 10, "SR": 35, "R": 55}, "flavor": "Noticeably better SR/SSR odds."},
    "elite":   {"label": "🏆 Elite Support Box",   "emoji": "🏆", "cost": 18_000,  "color": 0xFF4500, "weights": {"SSR": 25, "SR": 45, "R": 30}, "flavor": "SSR pulls start getting common."},
    "legend":  {"label": "👑 Legend Support Box",  "emoji": "👑", "cost": 50_000,  "color": 0xFFD700, "weights": {"SSR": 50, "SR": 45, "R": 5},  "flavor": "Mostly SR/SSR support cards."},
    "divine":  {"label": "✨ Divine Support Box",  "emoji": "✨", "cost": 150_000, "color": 0xFFFFFF, "weights": {"SSR": 80, "SR": 20, "R": 0},  "flavor": "Guaranteed SR or better, heavy odds on SSR."},
}

def _support_roll(weights_override: dict | None = None) -> dict:
    w = weights_override or _SUPPORT_RARITY_WEIGHTS
    valid = {r for r, wt in w.items() if wt > 0}
    filtered = [c for c in _SUPPORT_POOL if c[2] in valid]
    weights = [w[c[2]] for c in filtered]
    picked = random.choices(filtered, weights=weights, k=1)[0]
    return {"name": picked[0], "type": picked[1], "rarity": picked[2], "bonus": picked[3], "image": picked[4], "flavor": picked[5], "id": str(_uuid.uuid4())[:8]}

def _support_image(card: dict) -> str:
    img = card.get("image", "")
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

# ─────────────────────────────  Uma commands  ─────────────────────────────

@tree.command(name="lootbox_shop", description="🎁 View Umamusume loot box prices and odds")
async def lootbox_shop(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    embed = (EmbedBuilder(color=Palette.PRIMARY)
        .title("🎁 Umamusume Loot Box Shop")
        .description("Pick a box with `/lootbox <tier>`. Higher tiers cost more and improve Star odds."))
    for key, tier in _UMA_LOOTBOX_TIERS.items():
        odds = " • ".join(f"{rarity} `{weight:g}%`" for rarity, weight in tier["weights"].items() if weight > 0)
        embed.field(tier["label"], f"Cost: **{tier['cost']:,} Sayories**\n{tier['flavor']}\n{odds}", inline=False)
    await interaction.response.send_message(embed=embed.branded("Umamusume").build())

@tree.command(name="lootbox", description="🎁 Open an Umamusume loot box!")
@app_commands.describe(tier="Which box to open — higher tier = better odds & higher cost")
@app_commands.choices(tier=[app_commands.Choice(name="🎁 Basic     —   2,000 Sayories", value="basic"), app_commands.Choice(name="💎 Premium  —   8,000 Sayories", value="premium"), app_commands.Choice(name="🏆 Elite    —  25,000 Sayories", value="elite"), app_commands.Choice(name="👑 Legend   —  75,000 Sayories", value="legend"), app_commands.Choice(name="✨ Divine   — 200,000 Sayories", value="divine")])
async def lootbox(interaction: discord.Interaction, tier: str = "basic"):
    if not await dm_check(interaction): return
    t = _UMA_LOOTBOX_TIERS[tier]; cost = t["cost"]
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

    color = _UMA_RARITY_COLORS[uma["rarity"]]; remoji = _UMA_RARITY_EMOJI[uma["rarity"]]
    is_top = uma["rarity"] == "3-Star"

    top_text = '## 🎊 **3-STAR PULL!!!** 🎊\n' if is_top else ''
    reveal_embed = (EmbedBuilder(color=color)
        .title(f"{remoji} UNLOCKED: {uma['name']}  [{uma['rarity']}]")
        .description(f"{top_text}\n>>> *A new Uma has joined your team!*")
        .fields(("⚡ Speed", f"`{uma['speed']}`"), ("❤️ Stamina", f"`{uma['stamina']}`"), ("💪 Power", f"`{uma['power']}`"), ("🧠 Wit", f"`{uma.get('wit', 70)}`"), ("🔥 Guts", f"`{uma.get('guts', 70)}`"), ("🆔 Uma ID", f"`{uma['id']}`"))
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

    rarity_order = {"3-Star": 0, "2-Star": 1, "1-Star": 2}
    umas_sorted = sorted(umas, key=lambda u: (rarity_order.get(u.get("rarity", "1-Star"), 3), -_uma_power_score(u)))

    pages = []
    for u in umas_sorted:
        u.setdefault("wit", 70); u.setdefault("guts", 70)
        color = _UMA_RARITY_COLORS[u["rarity"]]; remoji = _UMA_RARITY_EMOJI[u["rarity"]]
        embed = (EmbedBuilder(color=color).title(f"{remoji} {u['name']} [{u['rarity']}]").description(f"🆔 ID: `{u['id']}` | 🏆 Race Record: **{u['wins']}W / {u['races']}R**\n⚡ **Overall Power Score:** `{_uma_power_score(u)}`").fields(("⚡ Speed", f"`{_stat_bar(u['speed'])}`"), ("❤️ Stamina", f"`{_stat_bar(u['stamina'])}`"), ("💪 Power", f"`{_stat_bar(u['power'])}`"), ("🧠 Wit", f"`{_stat_bar(u['wit'])}`"), ("🔥 Guts", f"`{_stat_bar(u['guts'])}`")).build())
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
    uma.setdefault("wit", 70)
    uma.setdefault("guts", 70)
    color = _UMA_RARITY_COLORS.get(uma.get("rarity", "1-Star"), Palette.PRIMARY)
    remoji = _UMA_RARITY_EMOJI.get(uma.get("rarity", "1-Star"), "🐴")
    embed = (EmbedBuilder(color=color)
        .title(f"{remoji} {uma['name']} [{uma['rarity']}]")
        .description(f"🆔 ID: `{uma['id']}` | 🏆 Race Record: **{uma['wins']}W / {uma['races']}R**\n⚡ **Overall Power Score:** `{_uma_power_score(uma)}`")
        .fields(("⚡ Speed", f"`{_stat_bar(uma['speed'])}`"), ("❤️ Stamina", f"`{_stat_bar(uma['stamina'])}`"), ("💪 Power", f"`{_stat_bar(uma['power'])}`"), ("🧠 Wit", f"`{_stat_bar(uma['wit'])}`"), ("🔥 Guts", f"`{_stat_bar(uma['guts'])}`"))
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

    base = {"3-Star": 3000, "2-Star": 900, "1-Star": 150}.get(uma.get("rarity", "1-Star"), 80)
    total = (uma.get("speed", 0) + uma.get("stamina", 0) + uma.get("power", 0) + uma.get("wit", 70) + uma.get("guts", 70))
    sell_price = base + (total // 5)

    confirmed = await ask_confirm(interaction, EmbedBuilder(color=Palette.WARNING).title("⚡ Fast Sell Uma").description(f"Are you sure you want to sell **{uma['name']}** [{uma['rarity']}]?\n\n💰 You'll receive: **{sell_price:,} Sayories** (minimum price)\n⚡ **Pwr Score:** `{_uma_power_score(uma)}`\n\n⚠️ **This cannot be undone!**").image(_uma_image(uma)).build(), confirm_label=f"Sell for {sell_price:,}")
    if not confirmed: return

    inv["umas"] = [u for u in inv["umas"] if u["id"] != uma_id]
    await _uma_save_inventory(interaction.user.id, inv)
    new_bal = await g_eco_add(interaction.user.id, sell_price)

    embed = (EmbedBuilder(color=Palette.SUCCESS).title("⚡ Uma Sold!").description(f"**{uma['name']}** [{uma['rarity']}] has been sold!\n\n💰 You received: **{sell_price:,} Sayories**\n💵 New balance: **{new_bal:,} Sayories**").thumbnail(interaction.user.display_avatar.url).footer("Tip: /lootbox opens another box when you're ready • Barm assistant 🐴").build())
    await interaction.followup.send(embed=embed)

# ─────────────────────────────  Support Card commands  ─────────────────────────────

@tree.command(name="support_shop", description="🎴 View Support Card loot box prices and odds")
async def support_shop(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    embed = (EmbedBuilder(color=Palette.PRIMARY)
        .title("🎴 Support Card Shop")
        .description("Pick a box with `/support_lootbox <tier>`. Support Cards train your Umas but can't be raced themselves — a separate pool from `/lootbox`."))
    for key, tier in _SUPPORT_LOOTBOX_TIERS.items():
        odds = " • ".join(f"{rarity} `{weight:g}%`" for rarity, weight in tier["weights"].items() if weight > 0)
        embed.field(tier["label"], f"Cost: **{tier['cost']:,} Sayories**\n{tier['flavor']}\n{odds}", inline=False)
    await interaction.response.send_message(embed=embed.branded("Umamusume").build())

@tree.command(name="support_lootbox", description="🎴 Open a Support Card loot box!")
@app_commands.describe(tier="Which box to open — higher tier = better odds & higher cost")
@app_commands.choices(tier=[app_commands.Choice(name="🎁 Basic     —   1,500 Sayories", value="basic"), app_commands.Choice(name="💎 Premium  —   6,000 Sayories", value="premium"), app_commands.Choice(name="🏆 Elite    —  18,000 Sayories", value="elite"), app_commands.Choice(name="👑 Legend   —  50,000 Sayories", value="legend"), app_commands.Choice(name="✨ Divine   — 150,000 Sayories", value="divine")])
async def support_lootbox(interaction: discord.Interaction, tier: str = "basic"):
    if not await dm_check(interaction): return
    t = _SUPPORT_LOOTBOX_TIERS[tier]; cost = t["cost"]
    bal = await g_eco_get(interaction.user.id)
    if bal < cost: return await interaction.response.send_message(f"❌ You need **{cost:,} Sayories** to open a **{t['label']}** (you have {bal:,}).", ephemeral=True)
    await g_eco_add(interaction.user.id, -cost)

    embed = (EmbedBuilder(color=t["color"]).title("🎴 SUPPORT DESK OPENING").description(f"```\n┌────────────────────────────────────────┐\n│  {t['emoji']} OPENING: {t['label']:<26} │\n│                                        │\n│      📋 REVIEWING CANDIDATES...        │\n│                                        │\n└────────────────────────────────────────┘\n```\n✨ *A new supporter steps forward...*").build())
    await interaction.response.send_message(embed=embed)
    await asyncio.sleep(1.5)

    card = _support_roll(weights_override=t["weights"])
    inv = await _support_get_inventory(interaction.user.id)
    inv.setdefault("cards", []).append(card)
    await _support_save_inventory(interaction.user.id, inv)

    color = _SUPPORT_RARITY_COLORS[card["rarity"]]; remoji = _SUPPORT_RARITY_EMOJI[card["rarity"]]; temoji = _SUPPORT_TYPE_EMOJI[card["type"]]
    is_top = card["rarity"] == "SSR"

    top_text = '## 🎊 **SSR PULL!!!** 🎊\n' if is_top else ''
    reveal_embed = (EmbedBuilder(color=color)
        .title(f"{remoji} UNLOCKED: {card['name']}  [{temoji} {card['type']} / {card['rarity']}]")
        .description(f"{top_text}\n>>> *{card['flavor']}*")
        .fields(("📊 Support Bonus", f"`{card['bonus']}`"), ("🆔 Card ID", f"`{card['id']}`"))
        .field(f"{t['emoji']} Box Used", f"**{t['label']}** — {cost:,} Sayories", inline=False)
        .build())
    img = _support_image(card)
    if img: reveal_embed.set_image(url=img)
    reveal_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    reveal_embed.set_footer(text=f"Cost: {cost:,} Sayories • Remaining: {bal - cost:,} 🪙")

    await interaction.edit_original_response(content="## 🎴 A NEW SUPPORTER JOINS YOUR DECK! 🎴", embed=reveal_embed)

@tree.command(name="support_inventory", description="🎴 View your Support Card collection (paginated with images)")
async def support_inventory(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    inv = await _support_get_inventory(interaction.user.id)
    cards = inv.get("cards", [])
    if not cards: return await interaction.response.send_message("🎴 You have no Support Cards! Open a `/support_lootbox` to get started.", ephemeral=True)

    rarity_order = {"SSR": 0, "SR": 1, "R": 2}
    cards_sorted = sorted(cards, key=lambda c: (rarity_order.get(c.get("rarity", "R"), 3), -c.get("bonus", 0)))

    pages = []
    for c in cards_sorted:
        color = _SUPPORT_RARITY_COLORS[c["rarity"]]; remoji = _SUPPORT_RARITY_EMOJI[c["rarity"]]; temoji = _SUPPORT_TYPE_EMOJI[c["type"]]
        embed = (EmbedBuilder(color=color).title(f"{remoji} {c['name']} [{temoji} {c['type']} / {c['rarity']}]").description(f"🆔 ID: `{c['id']}`\n*{c['flavor']}*").field("📊 Support Bonus", f"`{_stat_bar(c['bonus'], max_val=100)}`").build())
        img = _support_image(c)
        if img: embed.set_image(url=img)
        pages.append(embed)

    view = Paginator(pages, author_id=interaction.user.id)
    await interaction.response.send_message(embed=pages[0], view=view)

@tree.command(name="support_view", description="🎴 View a specific Support Card by ID")
@app_commands.describe(card_id="The Card ID from /support_inventory")
async def support_view(interaction: discord.Interaction, card_id: str):
    if not await dm_check(interaction): return
    inv = await _support_get_inventory(interaction.user.id)
    card = next((c for c in inv.get("cards", []) if c.get("id") == card_id), None)
    if not card:
        await interaction.response.send_message("❌ Support Card not found.", ephemeral=True)
        return
    color = _SUPPORT_RARITY_COLORS.get(card.get("rarity", "R"), Palette.PRIMARY)
    remoji = _SUPPORT_RARITY_EMOJI.get(card.get("rarity", "R"), "🎴")
    temoji = _SUPPORT_TYPE_EMOJI.get(card.get("type", "Speed"), "⚡")
    embed = (EmbedBuilder(color=color)
        .title(f"{remoji} {card['name']} [{temoji} {card['type']} / {card['rarity']}]")
        .description(f"🆔 ID: `{card['id']}`\n*{card['flavor']}*")
        .field("📊 Support Bonus", f"`{_stat_bar(card['bonus'], max_val=100)}`")
        .branded("Umamusume").build())
    img = _support_image(card)
    if img: embed.set_image(url=img)
    await interaction.response.send_message(embed=embed)

@tree.command(name="support_fastsell", description="⚡ Instantly sell your Support Card for the minimum price")
@app_commands.describe(card_id="The Card ID to sell (from /support_inventory)")
async def support_fastsell(interaction: discord.Interaction, card_id: str):
    if not await dm_check(interaction): return
    inv = await _support_get_inventory(interaction.user.id)
    card = next((c for c in inv.get("cards", []) if c["id"] == card_id), None)
    if not card: return await interaction.response.send_message("❌ Support Card not found.", ephemeral=True)

    base = {"SSR": 2500, "SR": 800, "R": 150}.get(card.get("rarity", "R"), 80)
    sell_price = base + (card.get("bonus", 0) * 10)

    confirmed = await ask_confirm(interaction, EmbedBuilder(color=Palette.WARNING).title("⚡ Fast Sell Support Card").description(f"Are you sure you want to sell **{card['name']}** [{card['type']} / {card['rarity']}]?\n\n💰 You'll receive: **{sell_price:,} Sayories** (minimum price)\n\n⚠️ **This cannot be undone!**").image(_support_image(card)).build(), confirm_label=f"Sell for {sell_price:,}")
    if not confirmed: return

    inv["cards"] = [c for c in inv["cards"] if c["id"] != card_id]
    await _support_save_inventory(interaction.user.id, inv)
    new_bal = await g_eco_add(interaction.user.id, sell_price)

    embed = (EmbedBuilder(color=Palette.SUCCESS).title("⚡ Support Card Sold!").description(f"**{card['name']}** [{card['rarity']}] has been sold!\n\n💰 You received: **{sell_price:,} Sayories**\n💵 New balance: **{new_bal:,} Sayories**").thumbnail(interaction.user.display_avatar.url).footer("Tip: /support_lootbox opens another box when you're ready • Barm assistant 🐴").build())
    await interaction.followup.send(embed=embed)

@tree.command(name="help", description="Show all Umamusume bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("umamusume", "Collect Umas and Support Cards with the shared Sayories economy.", {
        "🎁 Uma Gacha": ["`/lootbox_shop` — prices and odds", "`/lootbox <tier>` — open a box"],
        "🐴 Uma Collection": ["`/uma_inventory` — paginated collection", "`/uma_view <uma_id>` — inspect one Uma", "`/uma_fastsell <uma_id>` — sell one Uma instantly"],
        "🎴 Support Gacha": ["`/support_shop` — prices and odds", "`/support_lootbox <tier>` — open a box"],
        "📇 Support Collection": ["`/support_inventory` — paginated collection", "`/support_view <card_id>` — inspect one card", "`/support_fastsell <card_id>` — sell one card instantly"],
    })
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("UMAMUSUME_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the UMAMUSUME_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
