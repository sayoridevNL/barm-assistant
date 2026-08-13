from __future__ import annotations
import asyncio
import io
import json
import os
import random
import aiohttp

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

from shared import db_get_section, db_save_section
from theme import EmbedBuilder, Palette

try:
    from ui_kit import load_font
except ImportError:
    def load_font(size: int = 20):
        return ImageFont.load_default()

class CardsBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="c!", intents=discord.Intents.default())
        self.cards_db = []
        self.load_cards()

    def load_cards(self):
        try:
            with open("support_cards.json", "r", encoding="utf-8") as f:
                self.cards_db = json.load(f)
        except Exception as e:
            print(f"Failed to load cards: {e}")

    async def setup_hook(self):
        await self.tree.sync()

bot = CardsBot()

async def generate_card_image(card_data: dict) -> io.BytesIO:
    url = card_data.get("base_image", card_data.get("image_url", "")).replace("&width=100", "")
    
    img = None
    if url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        img = Image.open(io.BytesIO(data)).convert("RGBA")
        except:
            pass
            
    if not img:
        img = Image.new("RGBA", (250, 350), (40, 40, 40, 255))
        
    target_w, target_h = 250, 350
    w, h = img.size
    ratio = max(target_w / w, target_h / h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) / 2
    top = (new_h - target_h) / 2
    img = img.crop((left, top, left + target_w, top + target_h))
    
    draw = ImageDraw.Draw(img)
    
    rarity = card_data.get("rarity", "R")
    color = {"R": (52, 152, 219), "SR": (255, 215, 0), "SSR": (255, 0, 255)}.get(rarity, (255,255,255))
    draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=color, width=10)
    
    draw.rectangle([(0, target_h-50), (target_w, target_h)], fill=(0, 0, 0, 180))
    
    try:
        font = load_font("bold", 18)
    except:
        font = ImageFont.load_default()
    
    name = card_data.get("name", "Unknown Card")
    draw.text((15, target_h-35), name, fill=(255,255,255), font=font)
    
    card_type = card_data.get("type", "Unknown")
    type_colors = {
        "Speed": (135, 206, 235), "Stamina": (255, 165, 0),
        "Power": (255, 69, 0), "Guts": (255, 105, 180),
        "Intelligence": (50, 205, 50), "Friend": (255, 215, 0),
        "Group": (147, 112, 219)
    }
    t_col = type_colors.get(card_type, (255,255,255))
    draw.ellipse([(target_w-45, 15), (target_w-15, 45)], fill=t_col, outline=(255,255,255), width=2)
    draw.text((target_w-35, 20), card_type[0] if card_type else "?", fill=(255,255,255), font=font)
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

@bot.tree.command(name="buy_card", description="Buy a gacha card for 150 Sayories")
async def buy_card(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("Must be used in a server.", ephemeral=True)
        return

    eco = await db_get_section(guild_id, "economy")
    user_str = str(interaction.user.id)
    
    # check balance
    bal = eco.get(user_str, {}).get("balance", 0)
    if bal < 150:
        embed = EmbedBuilder(color=Palette.DANGER).title("Not enough Sayories!").description(f"You need 150 Sayories. You have {bal}.").build()
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # deduct balance
    eco.setdefault(user_str, {})["balance"] = bal - 150
    await db_save_section(guild_id, "economy", eco)
    
    # calculate drop
    roll = random.random()
    if roll < 0.02:
        rarity = "SSR"
    elif roll < 0.20:
        rarity = "SR"
    else:
        rarity = "R"
        
    pool = [c for c in bot.cards_db if c.get("rarity") == rarity]
    if not pool:
        pool = bot.cards_db
    if not pool:
        await interaction.response.send_message("No cards available in the database.", ephemeral=True)
        return
        
    card = random.choice(pool)
    
    # save to inventory
    inv = await db_get_section(guild_id, "inventory")
    user_inv = inv.get(user_str, {})
    card_id_str = str(card["id"])
    user_inv[card_id_str] = user_inv.get(card_id_str, 0) + 1
    inv[user_str] = user_inv
    await db_save_section(guild_id, "inventory", inv)
    
    await interaction.response.defer()
    
    # generate image
    img_buf = await generate_card_image(card)
    file = discord.File(img_buf, filename="card.png")
    
    embed = (EmbedBuilder(color=Palette.SUCCESS)
             .title(f"You pulled a {rarity} card!")
             .description(f"**{card.get('name')}**\nType: {card.get('type')}")
             .image("attachment://card.png")
             .footer(f"Remaining balance: {bal - 150}")
             .build())
             
    await interaction.followup.send(embed=embed, file=file)

@bot.tree.command(name="inventory", description="View your card collection")
async def inventory(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("Must be used in a server.", ephemeral=True)
        return
        
    # User's collection for guild 1049396166250475612 specifically, or current guild
    if guild_id != 1049396166250475612:
        guild_id = 1049396166250475612

    inv = await db_get_section(guild_id, "inventory")
    user_inv = inv.get(str(interaction.user.id), {})
    
    if not user_inv:
        await interaction.response.send_message("Your inventory is empty.", ephemeral=True)
        return
        
    lines = []
    for cid_str, count in user_inv.items():
        card = next((c for c in bot.cards_db if str(c.get("id")) == cid_str), None)
        if card:
            lines.append(f"**{card.get('name')}** ({card.get('rarity')}) x{count}")
            
    # Simple pagination using string chunks
    if not lines:
        await interaction.response.send_message("Your inventory is empty.", ephemeral=True)
        return
        
    pages = []
    chunk = []
    for line in lines:
        chunk.append(line)
        if len(chunk) == 10:
            pages.append("\n".join(chunk))
            chunk = []
    if chunk:
        pages.append("\n".join(chunk))
        
    embed = EmbedBuilder(color=Palette.INFO).title("Your Card Collection").description(pages[0]).footer(f"Page 1 of {len(pages)}").build()
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    print(f"Cards Bot connected as {bot.user}")

if __name__ == "__main__":
    bot.run(os.environ.get("DISCORD_TOKEN", ""))
