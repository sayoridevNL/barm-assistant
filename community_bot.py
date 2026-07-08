"""
community_bot.py — Server engagement systems (Sayories Tier leveling, Bocchies,
quotes, word tracker, counting channels, gameplay-VC pinger) and lightweight
fun commands.
"""
from __future__ import annotations
import os
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFilter

from shared import *
from shared import _global_lock, _load_global, _save_global, _db_lock, _db_load, _db_save
from theme import EmbedBuilder, Palette, Emojis, progress_bar
from ui_kit import (
    CooldownMap,
    install_error_handler, load_font, draw_gradient, draw_starfield,
    circular_avatar, to_discord_file, resolve_mentions,
    draw_text_with_fallback, truncate_text_pixels, wrap_text_pixels,
)

class CommunityBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="§unused-community§", intents=intents, help_command=None)
        self.xp_cd = CooldownMap(default_ttl=60.0)
        self.chat_cd = CooldownMap(default_ttl=60.0)
        self.bocchi_cd = CooldownMap(default_ttl=120.0)
        self._msg_count: dict[int | str, int | bool] = {}

    @tasks.loop(seconds=60)
    async def vc_payout_loop(self) -> None:
        vc_sayories = 3
        for guild in self.guilds:
            for vc in guild.voice_channels:
                for member in [m for m in vc.members if not m.bot]:
                    await self._pay_vc_member(guild, member, vc_sayories)

    async def _pay_vc_member(self, guild: discord.Guild, member: discord.Member, amount: int) -> None:
        async with _global_lock:
            gdata = _load_global()
            eco = gdata.setdefault("economy", {})
            uid = str(member.id)
            eco.setdefault(uid, {})
            old_bal = eco[uid].get("balance", 0)
            old_tier = tier_from_xp(old_bal)
            new_bal = old_bal + amount
            new_tier = tier_from_xp(new_bal)
            eco[uid]["balance"] = new_bal
            _save_global(gdata)

        if new_tier > old_tier and new_tier >= 1:
            await assign_tier_role(member, new_tier)

        nat_old = await bocchi_get(guild.id, member.id)
        nat_old_rank = bocchi_rank_from_points(nat_old)
        nat_new = await bocchi_add(guild.id, member.id, 1 if random.random() < 0.5 else 0)
        nat_new_rank = bocchi_rank_from_points(nat_new)
        if nat_new_rank > nat_old_rank and nat_new_rank >= 1:
            await bocchi_assign_rank_role(member, nat_new_rank)

    @tasks.loop(hours=168)
    async def weekly_reset(self) -> None:
        quotes = await global_get_section("quotes")
        if not quotes: return
        top_uid = max(quotes, key=lambda u: quotes[u].get("stars", 0))
        top_stars = quotes[top_uid].get("stars", 0)
        if top_stars == 0: return
        await g_eco_add(int(top_uid), 1000)
        await self._announce_weekly_winner(int(top_uid), top_stars)
        for uid in quotes: quotes[uid]["stars"] = 0
        await global_save_section("quotes", quotes)

    async def _announce_weekly_winner(self, winner_id: int, stars: int) -> None:
        for guild in self.guilds:
            member = guild.get_member(winner_id)
            if not member: continue
            embed = (EmbedBuilder(color=Palette.SAYORIES)
                .title(f"{Emojis.TROPHY} Weekly Quote Champion!")
                .description(f"### 🎊 {member.display_name} wins this week's global Quote Battle!\n\nThey earned **{stars} {Emojis.STAR}** and receive **1,000 Sayories** as a prize!\n\n*Stars reset for a new week. Good luck everyone!*")
                .thumbnail(member.display_avatar.url).branded("Quotes").build())
            for ch in guild.text_channels:
                try:
                    await ch.send(embed=embed)
                    return
                except discord.Forbidden: continue
                except Exception: continue
            return

    async def on_ready(self) -> None:
        print("🔄 Syncing community bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("community", self)
        self.vc_payout_loop.start()
        self.weekly_reset.start()
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["community"]["status"]))

bot = CommunityBot()
tree = bot.tree
install_error_handler(tree)

@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    if await sync_guild_safely(bot, guild): print(f"✅ Synced commands to new guild: {guild.name}")
    else: print(f"⚠️  Failed to sync to {guild.name}")

# ── IMAGE GENERATION ─────────────────────────────────────────────────────────




def _make_quote_card(*, quote_text: str, author_name: str, quoted_by: str, stars: int, avatar_bytes: bytes | None) -> discord.File:
    W, H, PAD = 1100, 420, 44
    AV_SIZE = 168
    AV_X = 48
    AV_Y = (H - AV_SIZE) // 2

    BLURPLE  = (88, 101, 242)
    GREEN    = (35, 165, 90)
    SURFACE  = (43, 45, 49)
    SURFACE2 = (35, 36, 40)
    WHITE    = (242, 243, 245)
    MUTED    = (181, 186, 193)
    DIM      = (116, 122, 130)

    img = Image.new("RGBA", (W, H), (*SURFACE, 255))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, (W, H), SURFACE, SURFACE2, direction="horizontal")
    draw_starfield(draw, (W, H), count=55, seed=7, brightness_range=(42, 82))
    draw.rectangle([(0, 0), (8, H)], fill=(*BLURPLE, 255))
    draw.rounded_rectangle([(28, 28), (W - 28, H - 28)], radius=22, outline=(255, 255, 255, 24), width=1)

    TEXT_X = AV_X + AV_SIZE + PAD
    RING = 6
    draw.ellipse([AV_X - RING, AV_Y - RING, AV_X + AV_SIZE + RING, AV_Y + AV_SIZE + RING], fill=(*BLURPLE, 70), outline=(*BLURPLE, 220), width=3)
    
    if avatar_bytes:
        try:
            av = circular_avatar(avatar_bytes, AV_SIZE)
            img.paste(av, (AV_X, AV_Y), av)
        except Exception:
            draw.ellipse([(AV_X, AV_Y), (AV_X + AV_SIZE, AV_Y + AV_SIZE)], fill=(*SURFACE2, 255), outline=(*BLURPLE, 160), width=2)
    else:
        draw.ellipse([(AV_X, AV_Y), (AV_X + AV_SIZE, AV_Y + AV_SIZE)], fill=(*SURFACE2, 255), outline=(*BLURPLE, 160), width=2)

    fnt_kicker   = load_font("bold", 16)
    fnt_bigquote = load_font("italic", 96)
    fnt_quote    = load_font("italic", 34)
    fnt_author   = load_font("bold", 26)
    fnt_handle   = load_font("regular", 18)
    fnt_footer   = load_font("regular", 15)

    draw.rounded_rectangle([(TEXT_X, 42), (TEXT_X + 170, 70)], radius=14, fill=(*BLURPLE, 70), outline=(*BLURPLE, 140), width=1)
    draw_text_with_fallback(draw, (TEXT_X + 16, 47), "QUOTE CAPTURED", fnt_kicker, (*MUTED, 255))
    draw.ellipse([(AV_X + AV_SIZE - 28, AV_Y + AV_SIZE - 28), (AV_X + AV_SIZE + 4, AV_Y + AV_SIZE + 4)], fill=(*SURFACE, 255))
    draw.ellipse([(AV_X + AV_SIZE - 23, AV_Y + AV_SIZE - 23), (AV_X + AV_SIZE - 1, AV_Y + AV_SIZE - 1)], fill=(*GREEN, 255))

    TEXT_W = W - TEXT_X - PAD
    quote_text = quote_text.strip() or "*[no text]*"
    lines = wrap_text_pixels(draw, quote_text, fnt_quote, TEXT_W - 28, max_lines=5)

    draw_text_with_fallback(draw, (TEXT_X - 12, 78), "\u201c", fnt_bigquote, (*BLURPLE, 110))
    LINE_H, TEXT_Y0 = 45, 112
    for i, line in enumerate(lines):
        draw_text_with_fallback(draw, (TEXT_X + 4, TEXT_Y0 + i * LINE_H), line, fnt_quote, (*WHITE, 255))

    text_bottom = TEXT_Y0 + len(lines) * LINE_H
    draw_text_with_fallback(draw, (W - PAD - 20, text_bottom - 24), "\u201d", fnt_bigquote, (*BLURPLE, 100), anchor="ra")

    author_y = max(text_bottom + 14, H - 104)
    draw.rectangle([(TEXT_X, author_y + 10), (TEXT_X + 20, author_y + 13)], fill=(*BLURPLE, 255))
    author_text = truncate_text_pixels(draw, author_name, fnt_author, TEXT_W - 38)
    handle_raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in author_name).strip("_") or "user"
    handle = truncate_text_pixels(draw, f"@{handle_raw}", fnt_handle, TEXT_W - 38)
    draw_text_with_fallback(draw, (TEXT_X + 30, author_y), author_text, fnt_author, (*WHITE, 255))
    draw_text_with_fallback(draw, (TEXT_X + 30, author_y + 32), handle, fnt_handle, (*MUTED, 220))

    sep_y = H - 42
    draw.line([(TEXT_X, sep_y), (W - PAD, sep_y)], fill=(255, 255, 255, 30), width=1)
    footer = truncate_text_pixels(draw, f"Quoted by {quoted_by}  •  {stars} ⭐  •  Barm Assistant", fnt_footer, TEXT_W)
    draw_text_with_fallback(draw, (TEXT_X, sep_y + 10), footer, fnt_footer, (*DIM, 230))
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(*BLURPLE, 90), width=1)

    return to_discord_file(img, filename="quote.png")

def _quote_fallback_message(author_name: str, quote_text: str, quoted_by_mention: str) -> str:
    safe_author = discord.utils.escape_markdown(author_name)
    safe_quote = discord.utils.escape_markdown(quote_text.strip() or "*[no text]*")
    safe_quote = safe_quote.replace("\n", "\n> ")
    if len(safe_quote) > 1500:
        safe_quote = safe_quote[:1497].rstrip() + "..."
    return f"✨ **{safe_author}**\n> {safe_quote}\n📌 Quoted by {quoted_by_mention}"

# ── ACTION GIFS ──────────────────────────────────────────────────────────────
_ACTION_GIFS = {
    "hug": ["https://media.tenor.com/i_7Sb0Z2ZJ8AAAAC/anime-hug.gif", "https://media.tenor.com/XaFRgCRk2hAAAAAC/hug-anime.gif"],
    "highfive": ["https://media.tenor.com/oAnN2O2UkHkAAAAC/high-five-anime.gif"],
    "slap": ["https://media.tenor.com/0omJP64mlA4AAAAC/anime-slap.gif"],
    "kill": ["https://media.tenor.com/1T2q0JnT2dcAAAAC/anime-kill.gif"],
    "handshake": ["https://media.tenor.com/L4-jT-JEjCYAAAAC/handshake-anime.gif"],
}
_ACTION_META = {
    "hug": {"emoji": "🤗", "color": 0xFF69B4, "verb": "hugs", "desc": "Warm anime hug incoming~"},
    "highfive": {"emoji": "🙌", "color": 0xFFD700, "verb": "high-fives", "desc": "Slap those hands together!"},
    "slap": {"emoji": "👋", "color": 0xFF4500, "verb": "slaps", "desc": "The wind-up... the swing..."},
    "kill": {"emoji": "⚔️", "color": 0x8B0000, "verb": "kills", "desc": "Moment of silence 🕯️"},
    "handshake": {"emoji": "🤝", "color": 0x00CED1, "verb": "shakes", "desc": "A deal has been struck."},
    "poke": {"emoji": "👉", "color": 0x9B59B6, "verb": "pokes", "desc": "Boop!"},
    "pat": {"emoji": "🫳", "color": 0xFFB7C5, "verb": "pats", "desc": "There, there..."},
    "bite": {"emoji": "🦷", "color": 0xE74C3C, "verb": "bites", "desc": "Nom!"},
}
_ACTION_KEYWORDS = {
    "hug": "hug", "highfive": "highfive", "high five": "highfive", "high-five": "highfive",
    "slap": "slap", "kill": "kill", "handshake": "handshake", "poke": "poke", "pat": "pat", "bite": "bite",
}

async def _send_action_embed(channel, actor, target, action, *, from_slash=False):
    meta = _ACTION_META.get(action)
    if not meta: return
    gifs = _ACTION_GIFS.get(action, [])
    if not gifs: return

    gif = random.choice(gifs)
    text = f"{actor.mention} {meta['verb']} {target.mention}!"
    embed = (EmbedBuilder(color=meta["color"])
        .description(f"## {meta['emoji']} {text}\n{meta['desc']}")
        .image(gif).footer(f"Requested by {actor.display_name}").build())

    if from_slash: await channel.followup.send(embed=embed)
    else: await channel.send(embed=embed)

_BOT_ALIASES = ("barm assistant", "sayori", "nokotan", "bocchi", "haru urara")

def _bot_addressed(message: discord.Message) -> bool:
    if bot.user in message.mentions: return True
    lc = message.content.lower()
    return any(alias in lc for alias in _BOT_ALIASES)

def _detect_action(content_lower: str) -> str | None:
    for keyword, action in _ACTION_KEYWORDS.items():
        if keyword in content_lower: return action
    return None

def _find_action_target(message: discord.Message) -> discord.User | None:
    mentions = [u for u in message.mentions if u.id != bot.user.id]
    target = next((u for u in mentions if u.id != message.author.id), None)
    if target: return target
    return next((u for u in mentions), None)

# ── MESSAGE PIPELINE ─────────────────────────────────────────────────────────
@bot.event
async def on_message(message: discord.Message) -> None:
    if message.guild and not message.author.bot:
        if await _handle_counting_message(message): return
    if not message.guild:
        await _handle_dm_quote(message)
        return
    await _handle_guild_message(message)

async def _handle_guild_message(message: discord.Message) -> None:
    if message.author.bot: return
    author = message.author
    guild = message.guild
    key = (guild.id, author.id)

    if bot.user in message.mentions and "potato" in message.content.lower():
        try: await message.add_reaction("🥔")
        except discord.HTTPException: pass

    if _bot_addressed(message):
        content_lower = message.content.lower()
        action = _detect_action(content_lower)
        target = _find_action_target(message)
        if action and target:
            await _send_action_embed(message.channel, author, target, action)

    if bot.xp_cd.check(key, ttl=60):
        await _award_chat_sayories(message, random.randint(5, 10))
    if bot.chat_cd.check(key, ttl=60):
        await g_eco_add(author.id, 2)
    if bot.bocchi_cd.check(key, ttl=120):
        gain = 1 if random.random() < 0.6 else 0
        await _award_chat_bocchies(message, gain)

    await _handle_drop_event(message)
    await _handle_word_tracker(message)
    await _handle_reply_quote(message)

async def _award_chat_sayories(message: discord.Message, gain: int) -> None:
    author = message.author
    async with _global_lock:
        gdata = _load_global()
        eco = gdata.setdefault("economy", {})
        uid = str(author.id)
        eco.setdefault(uid, {})
        old_bal = eco[uid].get("balance", 0)
        old_tier = tier_from_xp(old_bal)
        new_bal = old_bal + gain
        new_tier = tier_from_xp(new_bal)
        eco[uid]["balance"] = new_bal
        _save_global(gdata)

    if new_tier > old_tier and new_tier >= 1:
        await _announce_tier_up(message, new_tier, new_bal)

async def _announce_tier_up(message: discord.Message, tier: int, balance: int) -> None:
    author = message.author
    await assign_tier_role(author, tier)
    emoji = TIER_EMOJIS.get(tier, "⬆️")
    title = TIER_TITLES.get(tier, f"Tier {tier}")
    color = TIER_COLORS.get(tier, 0xFFFFFF)
    _, into, needed = xp_for_next_tier(balance)
    bar = progress_bar(into, needed)

    max_tier_note = ("*You have reached the pinnacle — **Tier 25: Sayorie Legend**!* 🌟" if tier >= 25 else f"*You've been granted the **Level {tier}** role!*")
    
    embed = (EmbedBuilder(color=color)
        .title(f"{emoji} Tier Up! → **Tier {tier}**")
        .description(f"### 🎉 Congratulations, {author.mention}!\n\nYou have ascended to **Tier {tier} — {title}** {emoji}\n\n**Sayories Progress:** {bar}\n`{into:,}` / `{needed:,}` Sayories to next tier\n\n{max_tier_note}")
        .thumbnail(author.display_avatar.url).footer(f"Barm assistant Tier System • Total Sayories: {balance:,}").build())
    await message.channel.send(embed=embed)

async def _award_chat_bocchies(message: discord.Message, gain: int) -> None:
    author = message.author
    guild = message.guild
    old_points = await bocchi_get(guild.id, author.id)
    old_rank = bocchi_rank_from_points(old_points)
    new_points = await bocchi_add(guild.id, author.id, gain)
    new_rank = bocchi_rank_from_points(new_points)

    if new_rank > old_rank and new_rank >= 1:
        await bocchi_assign_rank_role(author, new_rank)
        await _announce_bocchi_rank_up(message, new_rank, new_points)

async def _announce_bocchi_rank_up(message: discord.Message, rank: int, points: int) -> None:
    author = message.author
    n_emoji = BOCCHI_RANK_EMOJIS.get(rank, "🌸")
    n_title = BOCCHI_RANK_TITLES.get(rank, f"Tier {rank}")
    n_color = BOCCHI_RANK_COLORS.get(rank, 0xFF69B4)
    _, n_into, n_needed = bocchi_progress(points)
    n_bar = progress_bar(n_into, n_needed)

    is_max = rank >= 10
    embed = (EmbedBuilder(color=n_color)
        .title(f"{n_emoji} Bocchi Tier Up! → **Tier {rank}**")
        .description(f"### 🎀 Well done, {author.mention}!\n\nYou have reached **Tier {rank} — {n_title}** {n_emoji}\n\n**Bocchies Progress:** {n_bar}\n" + (f"`{n_into:,}` / `{n_needed:,}` Bocchies to next rank\n\n" if not is_max else "\n") + ("*You are the **Bocchi Legend** of this server!* 💗" if is_max else f"*You've been granted the **Tier {rank}** role in this server!*"))
        .thumbnail(author.display_avatar.url).footer(f"Barm assistant 🔥 Bocchies • This server only • Total: {points:,}").build())
    await message.channel.send(embed=embed)

async def _handle_drop_event(message: discord.Message) -> None:
    gid = message.guild.id
    bot._msg_count[gid] = bot._msg_count.get(gid, 0) + 1
    threshold_key = f"drop_threshold_{gid}"
    if threshold_key not in bot._msg_count:
        bot._msg_count[threshold_key] = bot._msg_count[gid] + random.randint(30, 100)

    active_key = f"drop_active_{gid}"
    amount_key = f"drop_amount_{gid}"

    if bot._msg_count.get(active_key, False):
        if message.content.strip().lower() == "claim":
            bot._msg_count[active_key] = False
            bot._msg_count[threshold_key] = bot._msg_count[gid] + random.randint(30, 100)
            drop_amount = bot._msg_count.get(amount_key, 100)
            new_bal = await g_eco_add(message.author.id, drop_amount)
            embed = (EmbedBuilder(color=Palette.SAYORIES).description(f"🏆 **{message.author.display_name}** claimed the bonus and got **+{drop_amount} Sayories!**\n💰 New balance: **{new_bal:,} Sayories**").footer("Barm assistant 🐴 • Haru Urara is watching").build())
            await message.channel.send(embed=embed)
        return

    if bot._msg_count[gid] >= bot._msg_count[threshold_key]:
        bot._msg_count[active_key] = True
        drop_amount = random.choice([50, 75, 100, 150, 200])
        bot._msg_count[amount_key] = drop_amount
        embed = (EmbedBuilder(color=Palette.SAYORIES).description(f"💎 A bonus Sayories drop has appeared! First person to type `claim` wins **+{drop_amount} Sayories!**").footer("Barm assistant 🐴 • Haru Urara is watching").build())
        await message.channel.send(embed=embed)

async def _handle_word_tracker(message: discord.Message) -> None:
    watched = await db_get_section(message.guild.id, "word_tracker")
    if not watched: return
    words_in_msg = message.content.lower().split()
    counts = await db_get_section(message.guild.id, "word_counts")
    uid_str = str(message.author.id)
    changed = False
    for word in watched:
        if word in words_in_msg:
            counts.setdefault(word, {})
            counts[word][uid_str] = counts[word].get(uid_str, 0) + words_in_msg.count(word)
            changed = True
    if changed: await db_save_section(message.guild.id, "word_counts", counts)

async def _handle_reply_quote(message: discord.Message) -> None:
    if message.reference is None or not _bot_addressed(message): return
    content_stripped = message.content.lower().replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "")
    for alias in _BOT_ALIASES: content_stripped = content_stripped.replace(alias, "")
    content_stripped = content_stripped.strip()
    if "quote" not in content_stripped: return

    try: ref = await message.channel.fetch_message(message.reference.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException): return

    if not ref or ref.author.id == message.author.id: return
    await _process_quote(message, ref)

async def _process_quote(trigger_msg: discord.Message, ref: discord.Message) -> None:
    quotes = await global_get_section("quotes")
    quid = str(ref.author.id)
    quotes.setdefault(quid, {"stars": 0})
    quotes[quid]["stars"] += 1
    await global_save_section("quotes", quotes)
    new_stars = quotes[quid]["stars"]

    raw_text = ref.content or "*[no text]*"
    quote_text = resolve_mentions(raw_text, guild=trigger_msg.guild)
    try: av_bytes = await ref.author.display_avatar.with_size(256).read()
    except (discord.HTTPException, discord.Forbidden): av_bytes = None

    try:
        quote_file = _make_quote_card(quote_text=quote_text, author_name=ref.author.display_name, quoted_by=trigger_msg.author.display_name, stars=new_stars, avatar_bytes=av_bytes)
        await trigger_msg.channel.send(file=quote_file)
    except Exception:
        await trigger_msg.channel.send(_quote_fallback_message(ref.author.display_name, quote_text, trigger_msg.author.mention))

    embed = (EmbedBuilder(color=Palette.QUOTE).description(f"⭐ **{trigger_msg.author.display_name}** quoted **{ref.author.display_name}**!\n**{ref.author.display_name}** now has **{new_stars} ⭐**").build())
    await trigger_msg.channel.send(embed=embed)

async def _handle_dm_quote(message: discord.Message) -> None:
    if message.author.bot: return
    if "quote" not in message.content.lower(): return
    if not message.reference:
        await message.channel.send("💡 **How to quote in DMs:** Reply to the message you want to quote, then include the word `quote` in your reply!")
        return
    try: ref = await message.channel.fetch_message(message.reference.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException): return

    if ref.author.id == message.author.id: await message.channel.send("💔 You can't quote yourself!", delete_after=5); return
    if ref.author.bot: await message.channel.send("🤖 You can't quote a bot.", delete_after=5); return
    if not ref.content and not ref.attachments: await message.channel.send("❌ That message has no text to quote.", delete_after=5); return

    quotes = await global_get_section("quotes")
    quid = str(ref.author.id)
    quotes.setdefault(quid, {"stars": 0})
    quotes[quid]["stars"] += 1
    await global_save_section("quotes", quotes)
    new_stars = quotes[quid]["stars"]

    quote_text = resolve_mentions(ref.content or "*[no text — see attachment]*")
    try: av_bytes = await ref.author.display_avatar.with_size(256).read()
    except (discord.HTTPException, discord.Forbidden): av_bytes = None

    try:
        quote_file = _make_quote_card(quote_text=quote_text, author_name=ref.author.display_name, quoted_by=message.author.display_name, stars=new_stars, avatar_bytes=av_bytes)
        await message.channel.send(file=quote_file)
    except Exception:
        await message.channel.send(_quote_fallback_message(ref.author.display_name, quote_text, message.author.mention))

    embed = (EmbedBuilder(color=Palette.QUOTE).description(f"⭐ **{message.author.display_name}** quoted **{ref.author.display_name}**!\n**{ref.author.display_name}** now has **{new_stars} ⭐** globally").build())
    await message.channel.send(embed=embed)

# ── COUNTING CHANNEL SYSTEM ──────────────────────────────────────────────────
import re as _re
_ROMAN_VALUES = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]

def _to_roman(n: int) -> str:
    if n <= 0: return ""
    result = ""
    for value, numeral in _ROMAN_VALUES:
        while n >= value: result += numeral; n -= value
    return result

def _from_roman(s: str) -> int | None:
    s = s.strip().upper()
    pattern = _re.compile(r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
    if not pattern.match(s) or s == "": return None
    roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for j in range(len(s)):
        val = roman_map[s[j]]
        if j + 1 < len(s) and roman_map[s[j + 1]] > val: total -= val
        else: total += val
    return total if total > 0 else None

COUNTING_MODES = {
    "counting": {"label": "Normal", "emoji": "🔢"}, "letter": {"label": "Letters", "emoji": "🔤"},
    "2-counting": {"label": "×2", "emoji": "2️⃣"}, "hexadecimal": {"label": "Hex", "emoji": "🔣"},
    "5-counting": {"label": "×5", "emoji": "5️⃣"}, "100-counting": {"label": "×100", "emoji": "💯"},
    "10-counting": {"label": "×10", "emoji": "🔟"}, "decimals": {"label": "Decimals", "emoji": "🔸"},
    "binary": {"label": "Binary", "emoji": "01"}, "roman": {"label": "Roman", "emoji": "🏛️"},
}

def _next_count_value(mode: str, current: int | float) -> str:
    if mode == "counting": return str(int(current) + 1)
    elif mode == "letter":
        n = int(current) + 1
        result = ""
        while n > 0: n, rem = divmod(n - 1, 26); result = chr(65 + rem) + result
        return result
    elif mode == "2-counting": return str(int(current) + 2)
    elif mode == "hexadecimal": return hex(int(current) + 1)[2:].upper()
    elif mode == "5-counting": return str(int(current) + 5)
    elif mode == "100-counting": return str(int(current) + 100)
    elif mode == "10-counting": return str(int(current) + 10)
    elif mode == "decimals":
        n = round(current * 10) + 1
        whole, frac = divmod(n, 10)
        return f"{whole}.{frac}"
    elif mode == "binary": return bin(int(current) + 1)[2:]
    elif mode == "roman": return _to_roman(int(current) + 1)
    return str(int(current) + 1)

def _parse_count_input(mode: str, text: str) -> int | float | None:
    text = text.strip()
    try:
        if mode == "counting": return int(text)
        elif mode == "letter":
            text = text.upper()
            if not _re.fullmatch(r"[A-Z]+", text): return None
            val = 0
            for ch in text: val = val * 26 + (ord(ch) - 64)
            return val
        elif mode == "2-counting":
            v = int(text); return v if v % 2 == 0 else None
        elif mode == "hexadecimal": return int(text, 16)
        elif mode == "5-counting":
            v = int(text); return v if v % 5 == 0 else None
        elif mode == "100-counting":
            v = int(text); return v if v % 100 == 0 else None
        elif mode == "10-counting":
            v = int(text); return v if v % 10 == 0 else None
        elif mode == "decimals":
            if not _re.fullmatch(r"\d+\.\d", text): return None
            return round(float(text), 1)
        elif mode == "binary":
            if not _re.fullmatch(r"[01]+", text): return None
            return int(text, 2)
        elif mode == "roman": return _from_roman(text)
    except ValueError: return None
    return None

async def _counting_get(guild_id: int) -> dict: return await db_get_section(guild_id, "counting") or {}
async def _counting_save(guild_id: int, data: dict) -> None: await db_save_section(guild_id, "counting", data)

async def _counting_add_score(guild_id: int, user_id: int, mode: str) -> None:
    uid = str(user_id)
    async with _db_lock(guild_id):
        d = _db_load(guild_id)
        lb = d.setdefault("counting_lb", {})
        lb.setdefault(uid, {})
        lb[uid]["total"] = lb[uid].get("total", 0) + 1
        lb[uid][mode] = lb[uid].get(mode, 0) + 1
        _db_save(guild_id, d)

async def _counting_get_lb(guild_id: int) -> dict:
    async with _db_lock(guild_id): return _db_load(guild_id).get("counting_lb", {})

async def _handle_counting_message(message: discord.Message) -> bool:
    if message.author.bot or not message.guild: return False
    guild_id = message.guild.id
    data = await _counting_get(guild_id)
    channels = data.get("channels", {})
    ch_id = str(message.channel.id)
    if ch_id not in channels: return False

    cfg = channels[ch_id]
    mode = cfg.get("mode", "counting")
    current = cfg.get("current", 0)
    last_user = cfg.get("last_user")

    text = message.content.strip()
    expected_str = _next_count_value(mode, current)
    parsed = _parse_count_input(mode, text)

    async def _fail(reason: str) -> None:
        try: await message.add_reaction("❌")
        except discord.HTTPException: pass
        embed = (EmbedBuilder(color=Palette.DANGER).title("❌ Wrong count!").description(f"**{message.author.display_name}** ruined it!\n\nExpected: `{expected_str}`\nYou typed: `{text}`\n\n*{reason}*\n\nThe count has been reset to **0**. Start again from `{_next_count_value(mode, 0)}`!").thumbnail(message.author.display_avatar.url).build())
        try: await message.channel.send(embed=embed)
        except discord.HTTPException: pass
        cfg["current"] = 0
        cfg["last_user"] = None
        await _counting_save(guild_id, data)

    if last_user == message.author.id:
        await _fail("You can't count twice in a row!"); return True
    if parsed is None:
        await _fail("That doesn't match this counting mode's format."); return True
    expected_val = _parse_count_input(mode, expected_str)
    if parsed != expected_val:
        await _fail(f"The next number should have been `{expected_str}`."); return True

    try: await message.add_reaction("✅")
    except discord.HTTPException: pass

    cfg["current"] = parsed
    cfg["last_user"] = message.author.id
    await _counting_save(guild_id, data)
    await _counting_add_score(guild_id, message.author.id, mode)

    milestones = {100, 500, 1000, 5000, 10000}
    numeric_val = int(parsed) if mode != "decimals" else round(parsed * 10)
    if numeric_val in milestones:
        embed = (EmbedBuilder(color=Palette.SAYORIES).title(f"🎉 Milestone reached: `{text}`!").description(f"Amazing! {message.author.mention} hit the **{text}** milestone!").build())
        try: await message.channel.send(embed=embed)
        except discord.HTTPException: pass
    return True

# ── GAMEPLAY VC SYSTEM ───────────────────────────────────────────────────────
async def _gvc_get(guild_id: int) -> dict: return await db_get_section(guild_id, "gameplay_vc") or {}
async def _gvc_save(guild_id: int, data: dict) -> None: await db_save_section(guild_id, "gameplay_vc", data)

async def _handle_gameplay_vc_cleanup(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
    if not before.channel: return
    data = await _gvc_get(member.guild.id)
    active = data.get("active_vcs", {})
    ch_id = str(before.channel.id)
    if ch_id not in active: return
    if len(before.channel.members) > 0: return
    active.pop(ch_id)
    await _gvc_save(member.guild.id, data)
    try: await before.channel.delete(reason="Gameplay session ended — VC empty")
    except (discord.HTTPException, discord.Forbidden) as e: print(f"[GameplayVC] Could not delete VC: {e}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
    await _handle_gameplay_vc_cleanup(member, before, after)

# ── SLASH COMMANDS ───────────────────────────────────────────────────────────
counting_group = app_commands.Group(name="counting", description="⚙️ Manage counting channels")

@counting_group.command(name="setup", description="Link a channel to a counting mode")
@app_commands.describe(mode="The counting mode to use", channel="Channel to use (defaults to current channel)")
@app_commands.choices(mode=[app_commands.Choice(name="🔢 Normal (1, 2, 3…)", value="counting"), app_commands.Choice(name="🔤 Letters (A, B, C…)", value="letter"), app_commands.Choice(name="2️⃣ ×2 (2, 4, 6…)", value="2-counting"), app_commands.Choice(name="🔣 Hexadecimal (1…9, A…F, 10…)", value="hexadecimal"), app_commands.Choice(name="5️⃣ ×5 (5, 10, 15…)", value="5-counting"), app_commands.Choice(name="💯 ×100 (100, 200…)", value="100-counting"), app_commands.Choice(name="🔟 ×10 (10, 20, 30…)", value="10-counting"), app_commands.Choice(name="🔸 Decimals (0.1, 0.2…)", value="decimals"), app_commands.Choice(name="🖥️ Binary (1, 10, 11…)", value="binary"), app_commands.Choice(name="🏛️ Roman (I, II, III…)", value="roman")])
@app_commands.checks.has_permissions(manage_channels=True)
async def counting_setup(interaction: discord.Interaction, mode: str, channel: discord.TextChannel | None = None) -> None:
    if not await guild_check(interaction):
        return
    ch = channel or interaction.channel
    guild_id = interaction.guild_id
    data = await _counting_get(guild_id)
    channels = data.setdefault("channels", {})
    channels[str(ch.id)] = {"mode": mode, "current": 0, "last_user": None}
    await _counting_save(guild_id, data)
    info = COUNTING_MODES.get(mode, {"label": mode, "emoji": "🔢"})
    first = _next_count_value(mode, 0)
    embed = (EmbedBuilder(color=Palette.SUCCESS).title(f"{info['emoji']} Counting Channel Set Up").description(f"{ch.mention} is now a **{info['label']}** counting channel!\n\nStart counting from `{first}`\n• Wrong number = reset to 0\n• You can't count twice in a row").footer("Use /counting reset to restart anytime").build())
    await interaction.response.send_message(embed=embed)

@counting_group.command(name="reset", description="Reset a counting channel back to the first value")
@app_commands.describe(channel="Channel to reset (defaults to current channel)")
@app_commands.checks.has_permissions(manage_channels=True)
async def counting_reset(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    if not await guild_check(interaction):
        return
    ch = channel or interaction.channel
    data = await _counting_get(interaction.guild_id)
    cfg = data.get("channels", {}).get(str(ch.id))
    if not cfg:
        await interaction.response.send_message(f"❌ {ch.mention} is not a counting channel yet.", ephemeral=True)
        return
    cfg["current"] = 0
    cfg["last_user"] = None
    await _counting_save(interaction.guild_id, data)
    mode = cfg.get("mode", "counting")
    info = COUNTING_MODES.get(mode, {"label": mode, "emoji": "🔢"})
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title(f"{info['emoji']} Counting Reset")
        .description(f"{ch.mention} has been reset.\n\nNext value: `{_next_count_value(mode, 0)}`")
        .branded("Counting").build())
    await interaction.response.send_message(embed=embed)

@counting_group.command(name="info", description="Show the current state of a counting channel")
@app_commands.describe(channel="Channel to inspect (defaults to current channel)")
async def counting_info(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    if not await guild_check(interaction):
        return
    ch = channel or interaction.channel
    data = await _counting_get(interaction.guild_id)
    cfg = data.get("channels", {}).get(str(ch.id))
    if not cfg:
        await interaction.response.send_message(f"❌ {ch.mention} is not a counting channel yet.", ephemeral=True)
        return
    mode = cfg.get("mode", "counting")
    info = COUNTING_MODES.get(mode, {"label": mode, "emoji": "🔢"})
    current = cfg.get("current", 0)
    last_user = cfg.get("last_user")
    embed = (EmbedBuilder(color=Palette.INFO)
        .title(f"{info['emoji']} Counting Status")
        .fields(
            ("Channel", ch.mention),
            ("Mode", info["label"]),
            ("Current", f"`{current}`"),
            ("Next", f"`{_next_count_value(mode, current)}`"),
            ("Last Counter", f"<@{last_user}>" if last_user else "Nobody yet"),
        )
        .branded("Counting").build())
    await interaction.response.send_message(embed=embed)

@counting_group.command(name="leaderboard", description="Show the server counting leaderboard")
async def counting_leaderboard(interaction: discord.Interaction) -> None:
    if not await guild_check(interaction):
        return
    lb = await _counting_get_lb(interaction.guild_id)
    if not lb:
        await interaction.response.send_message("No counting scores yet.")
        return
    top = sorted(lb.items(), key=lambda item: item[1].get("total", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (uid, stats) in enumerate(top, 1):
        name = f"<@{uid}>"
        badge = medals[idx - 1] if idx <= 3 else f"`{idx}.`"
        lines.append(f"{badge} **{name}** • `{stats.get('total', 0):,}` correct counts")
    embed = (EmbedBuilder(color=Palette.SAYORIES)
        .title("🏆 Counting Leaderboard")
        .description("\n".join(lines))
        .branded("Counting").build())
    await interaction.response.send_message(embed=embed)

tree.add_command(counting_group)

@tree.command(name="help", description="Show all Community bot commands")
async def help_cmd(interaction: discord.Interaction) -> None:
    embed = build_help_embed("community", "Server engagement, quotes, word games, and Bocchies — this bot runs the chat.", {"⬆️ Tiers & Bocchies": ["`/rank [member]`", "`/leaderboard`", "`/tiers`", "`/bocchi_rank [member]`"], "🔢 Utilities": ["`/counting setup|reset|info|leaderboard`"]})
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("COMMUNITY_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the COMMUNITY_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
