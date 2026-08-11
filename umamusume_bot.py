from __future__ import annotations
import os
import random
import time
import uuid as _uuid
import asyncio
import json

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

_UMA_POOL = []
def _load_uma_pool():
    global _UMA_POOL
    try:
        data_path = os.path.join(os.path.dirname(__file__), 'trainees.json')
        with open(data_path, 'r', encoding='utf-8') as f:
            _UMA_POOL = json.load(f)
    except Exception as e:
        print(f"Error loading trainees.json: {e}")

_load_uma_pool()

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
    if min_rarity == "2-Star": w["1-Star"] = 0
    elif min_rarity == "3-Star": w["1-Star"] = 0; w["2-Star"] = 0

    valid_rarities = {r for r, wt in w.items() if wt > 0}
    filtered = [u for u in _UMA_POOL if u["rarity"] in valid_rarities]
    if not filtered: return None
    weights = [w[u["rarity"]] for u in filtered]
    picked = random.choices(filtered, weights=weights, k=1)[0]
    
    # Base stats start at 1, but they retain their bonuses
    stars = int(picked["rarity"][0]) # 1, 2, or 3
    return {
        "name": picked["name"], "rarity": picked["rarity"], "character": picked.get("character", ""),
        "speed": 1, "stamina": 1, "power": 1, "wit": 1, "guts": 1,
        "speed_bonus": picked["speed_bonus"], "stamina_bonus": picked["stamina_bonus"],
        "power_bonus": picked["power_bonus"], "wit_bonus": picked["wit_bonus"], "guts_bonus": picked["guts_bonus"],
        "image": picked["image_url"], "wins": 0, "races": 0, "id": str(_uuid.uuid4())[:8],
        "stars": stars, "shards": 0
    }

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

_SUPPORT_POOL = []
def _load_support_pool():
    global _SUPPORT_POOL
    try:
        data_path = os.path.join(os.path.dirname(__file__), 'support_cards.json')
        with open(data_path, 'r', encoding='utf-8') as f:
            cards = json.load(f)
            
        for c in cards:
            rarity = c.get('rarity', 'R')
            if rarity == 'SSR': bonus = 80
            elif rarity == 'SR': bonus = 50
            else: bonus = 25
            
            ctype = c.get('type', 'Speed')
            if ctype == 'Pal': ctype = 'Friend'
                
            flavor = c.get('card_title', 'A reliable support card.')
            name = c.get('name', 'Unknown')
            image = c.get('image_url', '')
            _SUPPORT_POOL.append({"name": name, "type": ctype, "rarity": rarity, "bonus": bonus, "image": image, "flavor": flavor})
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
    if min_rarity == "SR": w["R"] = 0
    elif min_rarity == "SSR": w["R"] = 0; w["SR"] = 0

    valid = {r for r, wt in w.items() if wt > 0}
    filtered = [c for c in _SUPPORT_POOL if c["rarity"] in valid]
    weights = [w[c["rarity"]] for c in filtered]
    picked = random.choices(filtered, weights=weights, k=1)[0]
    return {"name": picked["name"], "type": picked["type"], "rarity": picked["rarity"], "bonus": picked["bonus"], "image": picked["image"], "flavor": picked["flavor"], "id": str(_uuid.uuid4())[:8], "uncaps": 0, "level": 1}

def _support_image(card: dict) -> str:
    img = card.get("image", "")
    if img:
        sep = "&" if "?" in img else "?"
        img = f"{img}{sep}_cb={int(time.time())}"
    return img

class UmamusumeBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="§unused-uma§", intents=discord.Intents.all(), help_command=None)

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
    if amount <= 0: return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    
    cost_per_coin = 100 if coin_type == "paid" else 1
    total_cost = amount * cost_per_coin
    bal = await g_eco_get(interaction.user.id)
    if bal < total_cost:
        return await interaction.response.send_message(f"❌ You need **{total_cost:,} Sayories** to buy {amount:,} {coin_type.capitalize()} Haru-Urara-Coins. (You have {bal:,})", ephemeral=True)
    
    await g_eco_add(interaction.user.id, -total_cost)
    if coin_type == "paid": await g_haru_add(interaction.user.id, 0, amount)
    else: await g_haru_add(interaction.user.id, amount, 0)
        
    f, p = await g_haru_get(interaction.user.id)
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title("🪙 Currency Converted!")
        .description(f"Successfully converted **{total_cost:,} Sayories** into **{amount:,} {coin_type.capitalize()} Haru-Urara-Coins**!")
        .fields(("Free Haru-Urara-Coins", f"`{f:,}`"), ("Paid Haru-Urara-Coins", f"`{p:,}`"), ("Remaining Sayories", f"`{bal - total_cost:,}`"))
        .build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="balance", description="🪙 Check your Haru-Urara-Coins and Sayories")
async def balance_cmd(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    bal = await g_eco_get(interaction.user.id)
    f, p = await g_haru_get(interaction.user.id)
    embed = (EmbedBuilder(color=Palette.PRIMARY).title("💰 Wallet Balance").fields(("Free Haru-Urara-Coins", f"`{f:,}`"), ("Paid Haru-Urara-Coins", f"`{p:,}`"), ("Sayories", f"`{bal:,}`")).build())
    await interaction.response.send_message(embed=embed)

# ─────────────────────────────  Pull Commands  ─────────────────────────────

def get_uma_duplicate_reward(rarity: str) -> int:
    return {"3-Star": 60, "2-Star": 10, "1-Star": 5}.get(rarity, 5)

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
        weights = _UMA_RARITY_WEIGHTS; guaranteed_rarity = "2-Star"
    else:
        if p < cost: return await interaction.response.send_message(f"❌ You need {cost:,} Paid Haru-Urara-Coins (You have {p:,}).", ephemeral=True)
        await g_haru_add(interaction.user.id, 0, -cost)
        weights = _PAID_UMA_WEIGHTS; guaranteed_rarity = "3-Star"

    await interaction.response.defer()
    
    inv = await _uma_get_inventory(interaction.user.id)
    umas = inv.setdefault("umas", [])
    
    pulls_display = []
    bonus_coins = {"free": 0, "paid": 0}
    
    for i in range(amount):
        min_rarity = "1-Star"
        if amount == 10 and i == 9: min_rarity = guaranteed_rarity
        rolled = _uma_roll(weights_override=weights, min_rarity=min_rarity)
        
        # Check duplicate
        existing = next((u for u in umas if u["name"] == rolled["name"]), None)
        if existing:
            shards_awarded = get_uma_duplicate_reward(rolled["rarity"])
            if existing.get("stars", 1) >= 5:
                # Max stars, give coins
                if rolled["rarity"] == "3-Star": bonus_coins["paid"] += 150
                elif rolled["rarity"] == "2-Star": bonus_coins["free"] += 150
                else: bonus_coins["free"] += 50
                pulls_display.append({"uma": rolled, "status": "max_stars", "coins": True})
            else:
                existing["shards"] = existing.get("shards", 0) + shards_awarded
                pulls_display.append({"uma": rolled, "status": "dup", "shards": shards_awarded})
        else:
            umas.append(rolled)
            pulls_display.append({"uma": rolled, "status": "new"})
            
    await _uma_save_inventory(interaction.user.id, inv)
    
    if bonus_coins["free"] > 0 or bonus_coins["paid"] > 0:
        await g_haru_add(interaction.user.id, bonus_coins["free"], bonus_coins["paid"])

    if amount == 1:
        pd = pulls_display[0]
        uma = pd["uma"]
        color = _UMA_RARITY_COLORS[uma["rarity"]]; remoji = _UMA_RARITY_EMOJI[uma["rarity"]]
        
        title_suffix = ""
        desc_text = ">>> *A new Uma has joined your team!*"
        if pd["status"] == "dup":
            title_suffix = " (DUPLICATE)"
            desc_text = f">>> *Duplicate! You received **{pd['shards']} Shards** for upgrading.*"
        elif pd["status"] == "max_stars":
            title_suffix = " (MAX STARS)"
            desc_text = ">>> *Duplicate at Max Stars! Converted to Haru-Urara-Coins.*"
            
        is_top = uma["rarity"] == "3-Star"
        top_text = '## 🎊 **3-STAR PULL!!!** 🎊\n' if is_top else ''
        embed = (EmbedBuilder(color=color)
            .title(f"{remoji} UNLOCKED: {uma['name']} {title_suffix}")
            .description(f"{top_text}{desc_text}")
            .fields(("⚡ Speed", f"`{uma['speed']}`"), ("❤️ Stamina", f"`{uma['stamina']}`"), ("💪 Power", f"`{uma['power']}`"), ("🧠 Wit", f"`{uma.get('wit', 1)}`"), ("🔥 Guts", f"`{uma.get('guts', 1)}`"), ("⭐ Initial Stars", f"`{uma['stars']}`"))
            .build())
        img = _uma_image(uma)
        if img: embed.set_image(url=img)
        await interaction.followup.send(content="## 🌸 THE GATES BURST OPEN... A NEW UMA APPEARS! 🌸", embed=embed)
    else:
        embeds = []
        for i, pd in enumerate(pulls_display):
            uma = pd["uma"]
            color = _UMA_RARITY_COLORS[uma["rarity"]]
            remoji = _UMA_RARITY_EMOJI[uma["rarity"]]
            
            st_text = "✨ NEW!"
            if pd["status"] == "dup": st_text = f"🔄 DUP (+{pd['shards']} Shards)"
            elif pd["status"] == "max_stars": st_text = "💰 MAX (Converted to Coins)"
            
            embed = (EmbedBuilder(color=color)
                .title(f"{remoji} {uma['name']} [{uma['rarity']}]")
                .description(f"**{st_text}**\n⚡`{uma['speed']}` ❤️`{uma['stamina']}` 💪`{uma['power']}` 🧠`{uma.get('wit', 1)}` 🔥`{uma.get('guts', 1)}`")
                .build())
            
            img = _uma_image(uma)
            if img: embed.set_image(url=img)
            embeds.append(embed)
            
        view = Paginator(embeds, author_id=interaction.user.id)
        msg = "## 🌸 10-PULL TRAINEE RESULTS 🌸\n*(Swipe to see all 10 pulls!)*"
        if sum(bonus_coins.values()) > 0:
            msg += f"\n💰 **Bonus Coins from Max Stars:** {bonus_coins['free']} Free, {bonus_coins['paid']} Paid"
        await interaction.followup.send(content=msg, embed=embeds[0], view=view)

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
        weights = _SUPPORT_RARITY_WEIGHTS; guaranteed_rarity = "SR" 
    else:
        if p < cost: return await interaction.response.send_message(f"❌ You need {cost:,} Paid Haru-Urara-Coins (You have {p:,}).", ephemeral=True)
        await g_haru_add(interaction.user.id, 0, -cost)
        weights = _PAID_SUPPORT_WEIGHTS; guaranteed_rarity = "SSR"

    await interaction.response.defer()
    
    inv = await _support_get_inventory(interaction.user.id)
    cards = inv.setdefault("cards", [])
    
    pulls_display = []
    bonus_coins = {"free": 0, "paid": 0}
    
    for i in range(amount):
        min_rarity = "R"
        if amount == 10 and i == 9: min_rarity = guaranteed_rarity
        rolled = _support_roll(weights_override=weights, min_rarity=min_rarity)
        
        # Check duplicate
        existing = next((c for c in cards if c["name"] == rolled["name"]), None)
        if existing:
            if existing.get("uncaps", 0) >= 4:
                # Max uncaps, give coins
                if rolled["rarity"] == "SSR": bonus_coins["paid"] += 150
                elif rolled["rarity"] == "SR": bonus_coins["free"] += 150
                else: bonus_coins["free"] += 50
                pulls_display.append({"card": rolled, "status": "max_uncap", "coins": True})
            else:
                existing["uncaps"] = existing.get("uncaps", 0) + 1
                pulls_display.append({"card": rolled, "status": "dup", "uncaps": existing["uncaps"]})
        else:
            cards.append(rolled)
            pulls_display.append({"card": rolled, "status": "new"})

    await _support_save_inventory(interaction.user.id, inv)
    
    if bonus_coins["free"] > 0 or bonus_coins["paid"] > 0:
        await g_haru_add(interaction.user.id, bonus_coins["free"], bonus_coins["paid"])

    if amount == 1:
        pd = pulls_display[0]
        card = pd["card"]
        color = _SUPPORT_RARITY_COLORS[card["rarity"]]; remoji = _SUPPORT_RARITY_EMOJI[card["rarity"]]; temoji = _SUPPORT_TYPE_EMOJI[card["type"]]
        
        title_suffix = ""
        desc_text = f">>> *{card['flavor']}*"
        if pd["status"] == "dup":
            title_suffix = f" (UNCAP +{pd['uncaps']})"
            desc_text += "\n*Duplicate! Card uncapped.*"
        elif pd["status"] == "max_uncap":
            title_suffix = " (MAX UNCAP)"
            desc_text += "\n*Duplicate at Max Uncap! Converted to coins.*"
            
        is_top = card["rarity"] == "SSR"
        top_text = '## 🎊 **SSR PULL!!!** 🎊\n' if is_top else ''
        embed = (EmbedBuilder(color=color)
            .title(f"{remoji} UNLOCKED: {card['name']} {title_suffix}")
            .description(f"{top_text}{desc_text}")
            .fields(("📊 Support Bonus", f"`{card['bonus']}`"), ("📈 Level", "`1/30`"))
            .build())
        img = _support_image(card)
        if img: embed.set_image(url=img)
        await interaction.followup.send(content="## 🎴 A NEW SUPPORTER JOINS YOUR DECK! 🎴", embed=embed)
    else:
        embeds = []
        for i, pd in enumerate(pulls_display):
            card = pd["card"]
            color = _SUPPORT_RARITY_COLORS[card["rarity"]]
            remoji = _SUPPORT_RARITY_EMOJI[card["rarity"]]
            temoji = _SUPPORT_TYPE_EMOJI[card["type"]]
            
            st_text = "✨ NEW!"
            if pd["status"] == "dup": st_text = f"🔄 DUP (Uncap {pd['uncaps']}/4)"
            elif pd["status"] == "max_uncap": st_text = "💰 MAX (Converted to Coins)"
            
            embed = (EmbedBuilder(color=color)
                .title(f"{remoji} {card['name']} [{temoji} {card['type']} / {card['rarity']}]")
                .description(f"**{st_text}**\n📊 Support Bonus: `{card['bonus']}`")
                .build())
                
            img = _support_image(card)
            if img: embed.set_image(url=img)
            embeds.append(embed)
            
        view = Paginator(embeds, author_id=interaction.user.id)
        msg = "## 🎴 10-PULL SUPPORT RESULTS 🎴\n*(Swipe to see all 10 pulls!)*"
        if sum(bonus_coins.values()) > 0:
            msg += f"\n💰 **Bonus Coins from Max Uncaps:** {bonus_coins['free']} Free, {bonus_coins['paid']} Paid"
        await interaction.followup.send(content=msg, embed=embeds[0], view=view)

# ─────────────────────────────  Upgrade Commands  ─────────────────────────────

def _get_star_cost(current_stars: int) -> int:
    costs = {1: 50, 2: 100, 3: 200, 4: 500}
    return costs.get(current_stars, 99999)

@tree.command(name="uma_upgrade", description="⭐ Upgrade an Uma's star rank using Shards")
@app_commands.describe(uma_name="Exact name of the Uma to upgrade")
async def uma_upgrade_cmd(interaction: discord.Interaction, uma_name: str):
    if not await dm_check(interaction): return
    inv = await _uma_get_inventory(interaction.user.id)
    umas = inv.get("umas", [])
    uma = next((u for u in umas if u["name"].lower() == uma_name.lower()), None)
    
    if not uma: return await interaction.response.send_message(f"❌ You don't own an Uma named '{uma_name}'.", ephemeral=True)
    
    stars = uma.get("stars", 1)
    if stars >= 5: return await interaction.response.send_message(f"❌ {uma['name']} is already at MAX STARS (5⭐).", ephemeral=True)
    
    cost = _get_star_cost(stars)
    shards = uma.get("shards", 0)
    
    if shards < cost:
        return await interaction.response.send_message(f"❌ You need {cost} shards to upgrade from {stars}⭐ to {stars+1}⭐. (You have {shards} shards). Pull more duplicates to get shards!", ephemeral=True)
        
    uma["shards"] -= cost
    uma["stars"] += 1
    
    # Optionally boost base stats slightly on star upgrade
    uma["speed"] += 5; uma["stamina"] += 5; uma["power"] += 5; uma["guts"] += 5; uma["wit"] += 5
    
    await _uma_save_inventory(interaction.user.id, inv)
    
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title(f"⭐ {uma['name']} upgraded to {uma['stars']} Stars!")
        .description(f"Cost: {cost} shards. Remaining: {uma['shards']}.")
        .build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="support_upgrade", description="🎴 Upgrade a Support Card's level using Sayories")
@app_commands.describe(card_name="Exact name of the Support Card to upgrade")
async def support_upgrade_cmd(interaction: discord.Interaction, card_name: str):
    if not await dm_check(interaction): return
    inv = await _support_get_inventory(interaction.user.id)
    cards = inv.get("cards", [])
    card = next((c for c in cards if c["name"].lower() == card_name.lower()), None)
    
    if not card: return await interaction.response.send_message(f"❌ You don't own a Support Card named '{card_name}'.", ephemeral=True)
    
    level = card.get("level", 1)
    uncaps = card.get("uncaps", 0)
    max_level = 30 + (uncaps * 5)
    
    if level >= max_level:
        return await interaction.response.send_message(f"❌ {card['name']} is already at max level {max_level} for its current uncap ({uncaps}/4). Pull duplicates to uncap!", ephemeral=True)
        
    cost = 2 ** level
    bal = await g_eco_get(interaction.user.id)
    
    if bal < cost:
        return await interaction.response.send_message(f"❌ You need {cost:,} Sayories to upgrade to level {level+1}. (You have {bal:,})", ephemeral=True)
        
    await g_eco_add(interaction.user.id, -cost)
    card["level"] += 1
    card["bonus"] += 1 # small bonus increase per level
    
    await _support_save_inventory(interaction.user.id, inv)
    
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title(f"📈 {card['name']} upgraded to Lv {card['level']}!")
        .description(f"Cost: {cost:,} Sayories.")
        .field("New Bonus", str(card["bonus"]))
        .build())
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────  Uma commands  ─────────────────────────────

@tree.command(name="uma_inventory", description="🐴 View your Umamusume collection (paginated with images)")
async def uma_inventory(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    inv = await _uma_get_inventory(interaction.user.id)
    umas = inv.get("umas", [])
    if not umas: return await interaction.response.send_message("🎁 You have no Umamusume! Run `/pull_trainee` to get started.", ephemeral=True)

    rarity_order = {"3-Star": 0, "2-Star": 1, "1-Star": 2}
    umas_sorted = sorted(umas, key=lambda u: (rarity_order.get(u.get("rarity", "1-Star"), 3), -u.get("stars", 1)))

    pages = []
    for u in umas_sorted:
        u.setdefault("wit", 1); u.setdefault("guts", 1)
        color = _UMA_RARITY_COLORS[u["rarity"]]; remoji = "⭐" * u.get("stars", 1)
        embed = (EmbedBuilder(color=color).title(f"{remoji} {u['name']} [{u['rarity']}]").description(f"🆔 ID: `{u['id']}` | 🏆 Race Record: **{u['wins']}W / {u['races']}R**\n⭐ Stars: `{u.get('stars', 1)}/5` | 💎 Shards: `{u.get('shards', 0)}`").fields(("⚡ Speed", f"`{u['speed']}`"), ("❤️ Stamina", f"`{u['stamina']}`"), ("💪 Power", f"`{u['power']}`"), ("🧠 Wit", f"`{u['wit']}`"), ("🔥 Guts", f"`{u['guts']}`")).build())
        img = _uma_image(u)
        if img: embed.set_image(url=img)
        pages.append(embed)

    view = Paginator(pages, author_id=interaction.user.id)
    await interaction.response.send_message(embed=pages[0], view=view)

@tree.command(name="support_inventory", description="🎴 View your Support Card collection (paginated with images)")
async def support_inventory(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    inv = await _support_get_inventory(interaction.user.id)
    cards = inv.get("cards", [])
    if not cards: return await interaction.response.send_message("🎴 You have no Support Cards! Run `/pull_support` to get started.", ephemeral=True)

    rarity_order = {"SSR": 0, "SR": 1, "R": 2}
    cards_sorted = sorted(cards, key=lambda c: (rarity_order.get(c.get("rarity", "R"), 3), -c.get("level", 1)))

    pages = []
    for c in cards_sorted:
        color = _SUPPORT_RARITY_COLORS[c["rarity"]]; remoji = _SUPPORT_RARITY_EMOJI[c["rarity"]]; temoji = _SUPPORT_TYPE_EMOJI.get(c.get("type", "Speed"), "⚡")
        embed = (EmbedBuilder(color=color).title(f"{remoji} {c['name']} [{temoji} {c['type']} / {c['rarity']}]").description(f"🆔 ID: `{c['id']}`\n*{c['flavor']}*").fields(("📈 Level", f"`{c.get('level', 1)}/{30 + (c.get('uncaps', 0) * 5)}`"), ("🔓 Uncaps", f"`{c.get('uncaps', 0)}/4`"), ("📊 Bonus", f"`{c['bonus']}`")).build())
        img = _support_image(c)
        if img: embed.set_image(url=img)
        pages.append(embed)

    view = Paginator(pages, author_id=interaction.user.id)
    await interaction.response.send_message(embed=pages[0], view=view)


@tree.command(name="help", description="Show all Umamusume bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("umamusume", "Use your Haru-Urara-Coins to pull Umas and Support Cards!", {
        "🪙 Currency": ["`/convert` — buy Haru-Urara-Coins", "`/balance` — check your wallets"],
        "🎁 Pulls (Gacha)": ["`/pull_trainee` — Pull 1 or 10 Umas", "`/pull_support` — Pull 1 or 10 Support Cards"],
        "🐴 Umas": ["`/uma_inventory` — paginated collection", "`/uma_upgrade` — upgrade star rank with shards"],
        "🎴 Support Cards": ["`/support_inventory` — paginated collection", "`/support_upgrade` — upgrade card level with Sayories"],
    })
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("UMAMUSUME_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the UMAMUSUME_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
