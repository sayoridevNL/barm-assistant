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
_UMA_RARITY_WEIGHTS = {"3-Star": 1, "2-Star": 8, "1-Star": 91}
_PAID_UMA_WEIGHTS = {"3-Star": 3, "2-Star": 12, "1-Star": 85}

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

def _uma_roll(weights_override: dict | None = None, min_rarity: str = "1-Star") -> dict:
    w = dict(weights_override or _UMA_RARITY_WEIGHTS)
    
    if min_rarity == "2-Star":
        w["1-Star"] = 0
    elif min_rarity == "3-Star":
        w["1-Star"] = 0
        w["2-Star"] = 0

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
_SUPPORT_RARITY_WEIGHTS = {"SSR": 1, "SR": 8, "R": 91}
_PAID_SUPPORT_WEIGHTS = {"SSR": 3, "SR": 12, "R": 85}

_SUPPORT_RARITY_COLORS  = {"SSR": 0xFF4500, "SR": 0x9B59B6, "R": 0x3498DB}
_SUPPORT_RARITY_EMOJI   = {"SSR": "🔶", "SR": "🔷", "R": "⬜"}
_SUPPORT_TYPE_EMOJI     = {"Speed": "⚡", "Stamina": "❤️", "Power": "💪", "Guts": "🔥", "Wit": "🧠", "Friend": "🤝", "Group": "👥"}
_SUPPORT_GLOBAL_SECTION = "uma_support_inventory"

import json
import os

_SUPPORT_POOL = []
def _load_support_pool():
    global _SUPPORT_POOL
    try:
        data_path = os.path.join(os.path.dirname(__file__), 'support_cards.json')
        with open(data_path, 'r', encoding='utf-8') as f:
            cards = json.load(f)
            
        for c in cards:
            # name, type, rarity, bonus, image, flavor
            rarity = c.get('rarity', 'R')
            if rarity == 'SSR':
                bonus = 80
            elif rarity == 'SR':
                bonus = 50
            else:
                bonus = 25
            
            # Map 'Pal' to 'Friend' if needed
            ctype = c.get('type', 'Speed')
            if ctype == 'Pal':
                ctype = 'Friend'
                
            flavor = c.get('card_title', 'A reliable support card.')
            name = c.get('name', 'Unknown')
            image = c.get('image_url', '')
            
            _SUPPORT_POOL.append((name, ctype, rarity, bonus, image, flavor))
    except Exception as e:
        print(f"Error loading support_cards.json: {e}")

_load_support_pool()

async def _support_get_inventory(user_id: int) -> dict:
    inv = await global_get_section(_SUPPORT_GLOBAL_SECTION)
    return inv.get(str(user_id), {})

async def _support_save_inventory(user_id: int, data: dict):
    inv_global = await global_get_section(_SUPPORT_GLOBAL_SECTION)
    inv_global[str(user_id)] = data
    await global_save_section(_SUPPORT_GLOBAL_SECTION, inv_global)

def _support_roll(weights_override: dict | None = None, min_rarity: str = "R") -> dict:
    w = dict(weights_override or _SUPPORT_RARITY_WEIGHTS)
    
    if min_rarity == "SR":
        w["R"] = 0
    elif min_rarity == "SSR":
        w["R"] = 0
        w["SR"] = 0

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

# ─────────────────────────────  Currency Commands  ─────────────────────────────

@tree.command(name="convert", description="🪙 Convert Sayories into Haru-Urara-Coins")
@app_commands.describe(amount="Amount of coins to buy", coin_type="Which coin to buy (Paid or Free)")
@app_commands.choices(coin_type=[app_commands.Choice(name="Free Haru-Urara-Coin (1 Sayories)", value="free"), app_commands.Choice(name="Paid Haru-Urara-Coin (100 Sayories)", value="paid")])
async def convert_cmd(interaction: discord.Interaction, amount: int, coin_type: str):
    if not await dm_check(interaction): return
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    
    cost_per_coin = 100 if coin_type == "paid" else 1
    total_cost = amount * cost_per_coin
    
    bal = await g_eco_get(interaction.user.id)
    if bal < total_cost:
        return await interaction.response.send_message(f"❌ You need **{total_cost:,} Sayories** to buy {amount:,} {coin_type.capitalize()} Haru-Urara-Coins. (You have {bal:,})", ephemeral=True)
    
    # Process transaction
    await g_eco_add(interaction.user.id, -total_cost)
    if coin_type == "paid":
        f, p = await g_haru_add(interaction.user.id, 0, amount)
    else:
        f, p = await g_haru_add(interaction.user.id, amount, 0)
        
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title("🪙 Currency Converted!")
        .description(f"Successfully converted **{total_cost:,} Sayories** into **{amount:,} {coin_type.capitalize()} Haru-Urara-Coins**!")
        .fields(
            ("Free Haru-Urara-Coins", f"`{f:,}`"),
            ("Paid Haru-Urara-Coins", f"`{p:,}`"),
            ("Remaining Sayories", f"`{bal - total_cost:,}`")
        ).build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="balance", description="🪙 Check your Haru-Urara-Coins and Sayories")
async def balance_cmd(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    bal = await g_eco_get(interaction.user.id)
    f, p = await g_haru_get(interaction.user.id)
    
    embed = (EmbedBuilder(color=Palette.PRIMARY)
        .title("💰 Wallet Balance")
        .fields(
            ("Free Haru-Urara-Coins", f"`{f:,}`"),
            ("Paid Haru-Urara-Coins", f"`{p:,}`"),
            ("Sayories", f"`{bal:,}`")
        ).build())
    await interaction.response.send_message(embed=embed)

# ─────────────────────────────  Pull Commands  ─────────────────────────────

@tree.command(name="pull_trainee", description="🐴 Pull for Trainee Umamusume")
@app_commands.describe(banner="Use Free or Paid Haru-Urara-Coins?", amount="Pull 1 or 10 times?")
@app_commands.choices(banner=[app_commands.Choice(name="Free Banner (Free Coins)", value="free"), app_commands.Choice(name="Premium Banner (Paid Coins)", value="paid")])
@app_commands.choices(amount=[app_commands.Choice(name="1 Pull (150 Coins)", value=1), app_commands.Choice(name="10 Pull (1,500 Coins) - Guaranteed Rarity!", value=10)])
async def pull_trainee_cmd(interaction: discord.Interaction, banner: str, amount: int):
    if not await dm_check(interaction): return
    cost = 150 * amount
    
    f, p = await g_haru_get(interaction.user.id)
    if banner == "free":
        if f < cost: return await interaction.response.send_message(f"❌ You need {cost:,} Free Haru-Urara-Coins (You have {f:,}).", ephemeral=True)
        await g_haru_add(interaction.user.id, -cost, 0)
        weights = _UMA_RARITY_WEIGHTS
        guaranteed_rarity = "2-Star" # Free 10-pull guarantees 2-Star (SR equivalent)
    else:
        if p < cost: return await interaction.response.send_message(f"❌ You need {cost:,} Paid Haru-Urara-Coins (You have {p:,}).", ephemeral=True)
        await g_haru_add(interaction.user.id, 0, -cost)
        weights = _PAID_UMA_WEIGHTS
        guaranteed_rarity = "3-Star" # Paid 10-pull guarantees 3-Star (SSR equivalent)

    await interaction.response.defer()
    
    # Generate Pulls
    pulls = []
    for i in range(amount):
        min_rarity = "1-Star"
        if amount == 10 and i == 9: # 10th pull is guaranteed
            min_rarity = guaranteed_rarity
        pulls.append(_uma_roll(weights_override=weights, min_rarity=min_rarity))

    # Save to Inventory
    inv = await _uma_get_inventory(interaction.user.id)
    inv.setdefault("umas", []).extend(pulls)
    await _uma_save_inventory(interaction.user.id, inv)

    if amount == 1:
        uma = pulls[0]
        color = _UMA_RARITY_COLORS[uma["rarity"]]; remoji = _UMA_RARITY_EMOJI[uma["rarity"]]
        is_top = uma["rarity"] == "3-Star"
        top_text = '## 🎊 **3-STAR PULL!!!** 🎊\n' if is_top else ''
        embed = (EmbedBuilder(color=color)
            .title(f"{remoji} UNLOCKED: {uma['name']}  [{uma['rarity']}]")
            .description(f"{top_text}\n>>> *A new Uma has joined your team!*")
            .fields(("⚡ Speed", f"`{uma['speed']}`"), ("❤️ Stamina", f"`{uma['stamina']}`"), ("💪 Power", f"`{uma['power']}`"), ("🧠 Wit", f"`{uma.get('wit', 70)}`"), ("🔥 Guts", f"`{uma.get('guts', 70)}`"), ("🆔 Uma ID", f"`{uma['id']}`"))
            .build())
        img = _uma_image(uma)
        if img: embed.set_image(url=img)
        await interaction.followup.send(content="## 🌸 THE GATES BURST OPEN... A NEW UMA APPEARS! 🌸", embed=embed)
    else:
        embeds = []
        pulls_sorted = sorted(pulls, key=lambda u: ({"3-Star": 0, "2-Star": 1, "1-Star": 2}.get(u["rarity"], 3)))
        
        for i, uma in enumerate(pulls_sorted):
            color = _UMA_RARITY_COLORS[uma["rarity"]]
            remoji = _UMA_RARITY_EMOJI[uma["rarity"]]
            
            embed = (EmbedBuilder(color=color)
                .title(f"{remoji} {uma['name']} [{uma['rarity']}]")
                .description(f"⚡`{uma['speed']}` ❤️`{uma['stamina']}` 💪`{uma['power']}` 🧠`{uma.get('wit', 70)}` 🔥`{uma.get('guts', 70)}`")
                .build())
            
            img = _uma_image(uma)
            if img: embed.set_image(url=img)
            embeds.append(embed)
            
        view = Paginator(embeds, author_id=interaction.user.id)
        await interaction.followup.send(content="## 🌸 10-PULL TRAINEE RESULTS 🌸\n*(Swipe to see all 10 pulls!)*", embed=embeds[0], view=view)

@tree.command(name="pull_support", description="🎴 Pull for Support Cards")
@app_commands.describe(banner="Use Free or Paid Haru-Urara-Coins?", amount="Pull 1 or 10 times?")
@app_commands.choices(banner=[app_commands.Choice(name="Free Banner (Free Coins)", value="free"), app_commands.Choice(name="Premium Banner (Paid Coins)", value="paid")])
@app_commands.choices(amount=[app_commands.Choice(name="1 Pull (150 Coins)", value=1), app_commands.Choice(name="10 Pull (1,500 Coins) - Guaranteed Rarity!", value=10)])
async def pull_support_cmd(interaction: discord.Interaction, banner: str, amount: int):
    if not await dm_check(interaction): return
    cost = 150 * amount
    
    f, p = await g_haru_get(interaction.user.id)
    if banner == "free":
        if f < cost: return await interaction.response.send_message(f"❌ You need {cost:,} Free Haru-Urara-Coins (You have {f:,}).", ephemeral=True)
        await g_haru_add(interaction.user.id, -cost, 0)
        weights = _SUPPORT_RARITY_WEIGHTS
        guaranteed_rarity = "SR" 
    else:
        if p < cost: return await interaction.response.send_message(f"❌ You need {cost:,} Paid Haru-Urara-Coins (You have {p:,}).", ephemeral=True)
        await g_haru_add(interaction.user.id, 0, -cost)
        weights = _PAID_SUPPORT_WEIGHTS
        guaranteed_rarity = "SSR"

    await interaction.response.defer()
    
    pulls = []
    for i in range(amount):
        min_rarity = "R"
        if amount == 10 and i == 9: 
            min_rarity = guaranteed_rarity
        pulls.append(_support_roll(weights_override=weights, min_rarity=min_rarity))

    inv = await _support_get_inventory(interaction.user.id)
    inv.setdefault("cards", []).extend(pulls)
    await _support_save_inventory(interaction.user.id, inv)

    if amount == 1:
        card = pulls[0]
        color = _SUPPORT_RARITY_COLORS[card["rarity"]]; remoji = _SUPPORT_RARITY_EMOJI[card["rarity"]]; temoji = _SUPPORT_TYPE_EMOJI[card["type"]]
        is_top = card["rarity"] == "SSR"
        top_text = '## 🎊 **SSR PULL!!!** 🎊\n' if is_top else ''
        embed = (EmbedBuilder(color=color)
            .title(f"{remoji} UNLOCKED: {card['name']}  [{temoji} {card['type']} / {card['rarity']}]")
            .description(f"{top_text}\n>>> *{card['flavor']}*")
            .fields(("📊 Support Bonus", f"`{card['bonus']}`"), ("🆔 Card ID", f"`{card['id']}`"))
            .build())
        img = _support_image(card)
        if img: embed.set_image(url=img)
        await interaction.followup.send(content="## 🎴 A NEW SUPPORTER JOINS YOUR DECK! 🎴", embed=embed)
    else:
        embeds = []
        pulls_sorted = sorted(pulls, key=lambda c: ({"SSR": 0, "SR": 1, "R": 2}.get(c["rarity"], 3)))
        
        for i, card in enumerate(pulls_sorted):
            color = _SUPPORT_RARITY_COLORS[card["rarity"]]
            remoji = _SUPPORT_RARITY_EMOJI[card["rarity"]]
            temoji = _SUPPORT_TYPE_EMOJI[card["type"]]
            
            embed = (EmbedBuilder(color=color)
                .title(f"{remoji} {card['name']} [{temoji} {card['type']} / {card['rarity']}]")
                .description(f"📊 Support Bonus: `{card['bonus']}`")
                .build())
                
            img = _support_image(card)
            if img: embed.set_image(url=img)
            embeds.append(embed)
            
        view = Paginator(embeds, author_id=interaction.user.id)
        await interaction.followup.send(content="## 🎴 10-PULL SUPPORT RESULTS 🎴\n*(Swipe to see all 10 pulls!)*", embed=embeds[0], view=view)

# ─────────────────────────────  Uma commands  ─────────────────────────────

@tree.command(name="uma_inventory", description="🐴 View your Umamusume collection (paginated with images)")
async def uma_inventory(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    inv = await _uma_get_inventory(interaction.user.id)
    umas = inv.get("umas", [])
    if not umas: return await interaction.response.send_message("🎁 You have no Umamusume! Run `/pull_trainee` to get started.", ephemeral=True)

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

@tree.command(name="uma_fastsell", description="⚡ Instantly sell your Uma for Haru-Urara-Coins")
@app_commands.describe(uma_id="The Uma ID to sell (from /uma_inventory)")
async def uma_fastsell(interaction: discord.Interaction, uma_id: str):
    if not await dm_check(interaction): return
    inv = await _uma_get_inventory(interaction.user.id)
    uma = next((u for u in inv.get("umas", []) if u["id"] == uma_id), None)
    if not uma: return await interaction.response.send_message("❌ Uma not found.", ephemeral=True)

    # Convert base values into Free Haru-Urara-Coins instead of Sayories
    base = {"3-Star": 30, "2-Star": 9, "1-Star": 1}.get(uma.get("rarity", "1-Star"), 1)
    
    confirmed = await ask_confirm(interaction, EmbedBuilder(color=Palette.WARNING).title("⚡ Fast Sell Uma").description(f"Are you sure you want to sell **{uma['name']}** [{uma['rarity']}]?\n\n💰 You'll receive: **{base:,} Free Haru-Urara-Coins**\n⚡ **Pwr Score:** `{_uma_power_score(uma)}`\n\n⚠️ **This cannot be undone!**").image(_uma_image(uma)).build(), confirm_label=f"Sell for {base:,} Coins")
    if not confirmed: return

    inv["umas"] = [u for u in inv["umas"] if u["id"] != uma_id]
    await _uma_save_inventory(interaction.user.id, inv)
    f, p = await g_haru_add(interaction.user.id, base, 0)

    embed = (EmbedBuilder(color=Palette.SUCCESS).title("⚡ Uma Sold!").description(f"**{uma['name']}** [{uma['rarity']}] has been sold!\n\n💰 You received: **{base:,} Free Haru-Urara-Coins**\n💵 New Free Coins balance: **{f:,}**").thumbnail(interaction.user.display_avatar.url).build())
    await interaction.followup.send(embed=embed)

# ─────────────────────────────  Support Card commands  ─────────────────────────────

@tree.command(name="support_inventory", description="🎴 View your Support Card collection (paginated with images)")
async def support_inventory(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    inv = await _support_get_inventory(interaction.user.id)
    cards = inv.get("cards", [])
    if not cards: return await interaction.response.send_message("🎴 You have no Support Cards! Run `/pull_support` to get started.", ephemeral=True)

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

@tree.command(name="support_fastsell", description="⚡ Instantly sell your Support Card for Haru-Urara-Coins")
@app_commands.describe(card_id="The Card ID to sell (from /support_inventory)")
async def support_fastsell(interaction: discord.Interaction, card_id: str):
    if not await dm_check(interaction): return
    inv = await _support_get_inventory(interaction.user.id)
    card = next((c for c in inv.get("cards", []) if c["id"] == card_id), None)
    if not card: return await interaction.response.send_message("❌ Support Card not found.", ephemeral=True)

    base = {"SSR": 25, "SR": 8, "R": 1}.get(card.get("rarity", "R"), 1)

    confirmed = await ask_confirm(interaction, EmbedBuilder(color=Palette.WARNING).title("⚡ Fast Sell Support Card").description(f"Are you sure you want to sell **{card['name']}** [{card['type']} / {card['rarity']}]?\n\n💰 You'll receive: **{base:,} Free Haru-Urara-Coins**\n\n⚠️ **This cannot be undone!**").image(_support_image(card)).build(), confirm_label=f"Sell for {base:,} Coins")
    if not confirmed: return

    inv["cards"] = [c for c in inv["cards"] if c["id"] != card_id]
    await _support_save_inventory(interaction.user.id, inv)
    f, p = await g_haru_add(interaction.user.id, base, 0)

    embed = (EmbedBuilder(color=Palette.SUCCESS).title("⚡ Support Card Sold!").description(f"**{card['name']}** [{card['rarity']}] has been sold!\n\n💰 You received: **{base:,} Free Haru-Urara-Coins**\n💵 New Free Coins balance: **{f:,}**").thumbnail(interaction.user.display_avatar.url).build())
    await interaction.followup.send(embed=embed)

@tree.command(name="help", description="Show all Umamusume bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("umamusume", "Use your Haru-Urara-Coins to pull Umas and Support Cards!", {
        "🪙 Currency": ["`/convert` — buy Haru-Urara-Coins", "`/balance` — check your wallets"],
        "🎁 Pulls (Gacha)": ["`/pull_trainee` — Pull 1 or 10 Umas", "`/pull_support` — Pull 1 or 10 Support Cards"],
        "🐴 Uma Collection": ["`/uma_inventory` — paginated collection", "`/uma_view <uma_id>` — inspect one Uma", "`/uma_fastsell <uma_id>` — sell one Uma instantly"],
        "📇 Support Collection": ["`/support_inventory` — paginated collection", "`/support_view <card_id>` — inspect one card", "`/support_fastsell <card_id>` — sell one card instantly"],
    })
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("UMAMUSUME_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the UMAMUSUME_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
