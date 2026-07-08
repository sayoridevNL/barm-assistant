from __future__ import annotations
import asyncio
import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from shared import *
from shared import _global_lock, _load_global, _save_global
from theme import EmbedBuilder, Palette
from ui_kit import install_error_handler
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from ui_kit import (
    draw_gradient, draw_starfield, circular_avatar, load_font,
    draw_text_with_fallback, to_discord_file, truncate_text_pixels
)

class LeaveServerView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        self.guild = guild

    @discord.ui.button(label="🚪 Remove from server", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != BOT_OWNER_ID:
            return await interaction.response.send_message("Only the bot owner can do this.", ephemeral=True)
        try:
            await self.guild.leave()
            await interaction.response.edit_message(content=f"✅ Left **{self.guild.name}**.", view=None)
        except Exception as e:
            await interaction.response.send_message(f"❌ Could not leave {self.guild.name}: {e}", ephemeral=True)

async def _send_server_list_to_owner(bot_ref):
    try: owner = await bot_ref.fetch_user(BOT_OWNER_ID)
    except Exception: return
    if owner is None: return
    guilds = list(bot_ref.guilds)
    if not guilds: return
    try: await owner.send(f"🤖 **Bot is online!** Currently in **{len(guilds)}** server(s). Use the buttons below to remove the bot from any of them.")
    except discord.Forbidden: return
    for guild in guilds:
        embed = (EmbedBuilder(color=Palette.PRIMARY).title(f"🏠 {guild.name}").fields(("🆔 ID", str(guild.id)), ("👥 Members", f"{guild.member_count:,}"), ("👑 Owner", f"<@{guild.owner_id}>")).build())
        if guild.icon: embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text="Click below to remove the bot from this server.")
        try:
            await owner.send(embed=embed, view=LeaveServerView(guild))
            await asyncio.sleep(0.5)
        except discord.Forbidden: break
        except Exception: pass

SAYORIES_THEME = {"bg": (5, 12, 22), "bg2": (23, 30, 48), "accent": (0, 255, 208), "accent2": (0, 220, 175), "accent3": (0, 120, 100), "white": (235, 240, 245), "dim": (100, 130, 150)}
BOCCHI_THEME = {"bg": (16, 4, 1), "bg2": (38, 10, 4), "accent": (255, 200, 0), "accent2": (210, 100, 10), "accent3": (130, 45, 5), "white": (248, 238, 222), "dim": (160, 105, 70)}

def _make_rank_card(*, display_name: str, username: str, avatar_bytes: bytes | None, tier: int, tier_title: str, total_xp: int, xp_into: int, xp_needed: int, rank_pos: int | str, balance: int, theme: dict, filename: str = "rank_card.png") -> discord.File:
    W, H, PAD = 1024, 347, 32
    AV = 148
    AV_X = PAD + 14
    AV_Y = (H - AV) // 2

    img = Image.new("RGBA", (W, H), (*theme["bg"], 255))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, (W, H), theme["bg"], theme["bg2"], direction="horizontal")
    draw_starfield(draw, (W, H), count=130, seed=42, brightness_range=(55, 190))

    for x in range(4):
        alpha = 255 - x * 30
        draw.line([(x, 0), (x, H)], fill=(*theme["accent"], alpha))

    cx, cy = AV_X + AV // 2, AV_Y + AV // 2
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r_off in range(28, 0, -1):
        alpha = int(160 * (1 - r_off / 28) ** 1.4)
        rad = AV // 2 + r_off
        gd.ellipse([(cx - rad, cy - rad), (cx + rad, cy + rad)], outline=(*theme["accent"], alpha), width=2)
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(radius=4)))
    draw = ImageDraw.Draw(img)

    draw.ellipse([(AV_X - 4, AV_Y - 4), (AV_X + AV + 4, AV_Y + AV + 4)], outline=(*theme["accent"], 255), width=3)

    if avatar_bytes:
        try:
            av = circular_avatar(avatar_bytes, AV)
            img.paste(av, (AV_X, AV_Y), av)
            draw = ImageDraw.Draw(img)
        except Exception:
            draw.ellipse([(AV_X, AV_Y), (AV_X + AV, AV_Y + AV)], fill=(20, 35, 50, 255))
    else:
        draw.ellipse([(AV_X, AV_Y), (AV_X + AV, AV_Y + AV)], fill=(20, 35, 50, 255))

    bx, by = AV_X + AV - 14, AV_Y + AV - 14
    draw.ellipse([(bx - 17, by - 17), (bx + 17, by + 17)], fill=(*theme["bg"], 255), outline=(*theme["accent"], 255), width=2)
    fnt_lbl = load_font("bold", 15)
    draw_text_with_fallback(draw, (bx, by), str(tier) if tier > 0 else "?", fnt_lbl, (*theme["accent"], 255), anchor="mm")

    TX, TY = AV_X + AV + 28, PAD + 6
    fnt_name = load_font("bold", 34)
    fnt_sub  = load_font("regular", 18)
    fnt_tier = load_font("bold", 22)
    fnt_rank = load_font("bold", 56)
    fnt_rlbl = load_font("regular", 13)
    fnt_bar  = load_font("bold", 22)
    fnt_foot = load_font("regular", 15)

    display_name = truncate_text_pixels(draw, display_name, fnt_name, W - TX - 230)
    username = truncate_text_pixels(draw, f"@{username}", fnt_sub, W - TX - 230)
    draw_text_with_fallback(draw, (TX, TY), display_name, fnt_name, (*theme["white"], 255))
    draw_text_with_fallback(draw, (TX, TY + 42), username, fnt_sub, (*theme["dim"], 255))

    dot_r = 7
    dot_y = TY + 80
    draw.ellipse([(TX, dot_y), (TX + dot_r * 2, dot_y + dot_r * 2)], fill=(*theme["accent"], 255))
    tier_label = f"Level {tier} — {tier_title}" if tier > 0 else "Unranked"
    tier_label = truncate_text_pixels(draw, tier_label, fnt_tier, W - TX - 220)
    draw_text_with_fallback(draw, (TX + dot_r * 2 + 10, dot_y - 1), tier_label, fnt_tier, (*theme["accent"], 255))

    TR = W - PAD
    draw_text_with_fallback(draw, (TR, PAD - 6), f"#{rank_pos}", fnt_rank, (*theme["accent"], 255), anchor="ra")
    draw_text_with_fallback(draw, (TR, PAD + 56), "GLOBAL RANK", fnt_rlbl, (*theme["dim"], 255), anchor="ra")

    BAR_H = 48
    BAR_X0 = TX
    BAR_X1 = W - PAD
    BAR_W = BAR_X1 - BAR_X0
    BAR_Y0 = H - PAD - BAR_H - 26
    BAR_Y1 = BAR_Y0 + BAR_H
    BAR_R = BAR_H // 2

    bar_glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(bar_glow).rounded_rectangle([(BAR_X0 - 6, BAR_Y0 - 6), (BAR_X1 + 6, BAR_Y1 + 6)], radius=BAR_R + 6, fill=(*theme["accent"], 50))
    img = Image.alpha_composite(img, bar_glow.filter(ImageFilter.GaussianBlur(radius=8)))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([(BAR_X0, BAR_Y0), (BAR_X1, BAR_Y1)], radius=BAR_R, fill=(8, 22, 36, 255), outline=(*theme["accent3"], 200), width=1)

    if xp_needed > 0 and xp_into > 0:
        fill_w = max(BAR_R * 2, int((xp_into / xp_needed) * BAR_W))
        fill_w = min(fill_w, BAR_W)
        fill_img = Image.new("RGBA", (fill_w, BAR_H), (0, 0, 0, 0))
        ImageDraw.Draw(fill_img).rounded_rectangle([(0, 0), (fill_w - 1, BAR_H - 1)], radius=BAR_R, fill=(*theme["accent2"], 255))
        img.paste(fill_img, (BAR_X0, BAR_Y0), fill_img)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([(BAR_X0, BAR_Y0), (BAR_X1, BAR_Y1)], radius=BAR_R, outline=(*theme["accent2"], 180), width=1)
    elif xp_needed == 0:
        draw.rounded_rectangle([(BAR_X0, BAR_Y0), (BAR_X1, BAR_Y1)], radius=BAR_R, fill=(*theme["accent"], 255), outline=(*theme["accent2"], 200), width=1)

    if xp_needed > 0:
        to_go = xp_needed - xp_into
        bar_text = f"{xp_into:,} / {xp_needed:,} Sayories  ({to_go:,} to go)"
    else:
        bar_text = f"MAX TIER — {balance:,} Sayories"
    bar_cx = (BAR_X0 + BAR_X1) // 2
    bar_cy = (BAR_Y0 + BAR_Y1) // 2
    bar_text = truncate_text_pixels(draw, bar_text, fnt_bar, BAR_W - 28)
    draw_text_with_fallback(draw, (bar_cx, bar_cy), bar_text, fnt_bar, (*theme["white"], 255), anchor="mm")

    foot_y = BAR_Y1 + 9
    draw_text_with_fallback(draw, (BAR_X0, foot_y), f"Total Sayories: {balance:,}", fnt_foot, (*theme["dim"], 255))
    if tier < 25 and xp_needed > 0:
        nxt = f"Next: Tier {tier + 1} — {TIER_TITLES.get(tier + 1, '')}  ✦"
    else:
        nxt = "👑 MAX TIER — Sayorie Legend"
    nxt = truncate_text_pixels(draw, nxt, fnt_foot, BAR_W // 2)
    draw_text_with_fallback(draw, (BAR_X1, foot_y), nxt, fnt_foot, (*theme["accent2"], 255), anchor="ra")

    return to_discord_file(img, filename=filename)

class GeneralBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="§unused-general§", intents=intents, help_command=None)
        self._work_cd: dict[tuple, float] = {}

    async def on_guild_join(self, guild: discord.Guild):
        if await sync_guild_safely(self, guild): print(f"✅ Synced commands to new guild: {guild.name}")
        else: print(f"⚠️  Failed to sync to {guild.name}")
        owner = await self.fetch_user(BOT_OWNER_ID)
        if owner is None: return
        embed = (EmbedBuilder(color=Palette.PRIMARY).title("🔔 Joined a New Server").fields(("🏠 Server", guild.name), ("🆔 ID", str(guild.id)), ("👥 Members", f"{guild.member_count:,}"), ("👑 Owner", f"<@{guild.owner_id}>")).build())
        if guild.icon: embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text="Click below to remove the bot from this server.")
        try: await owner.send(embed=embed, view=LeaveServerView(guild))
        except discord.Forbidden: pass

    async def on_ready(self):
        print("🔄 Syncing general bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("general", self)
        asyncio.create_task(_send_server_list_to_owner(self))
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["general"]["status"]))

bot = GeneralBot()
tree = bot.tree

@tree.command(name="rank", description="View your or another member's tier & rank card")
@app_commands.describe(member="Member to check (leave blank for yourself)")
async def rank(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    if not await dm_check(interaction): return
    await interaction.response.defer()
    target = member or interaction.user
    balance = await g_eco_get(target.id)
    ct, into, needed = xp_for_next_tier(balance)

    emoji = TIER_EMOJIS.get(ct, "🌱") if ct > 0 else "🌑"
    title = TIER_TITLES.get(ct, "Unranked") if ct > 0 else "Unranked"
    color = TIER_COLORS.get(ct, 0x808080)

    eco_data = await global_get_section("economy")
    all_sorted = sorted(eco_data.items(), key=lambda x: x[1].get("balance", 0), reverse=True)
    position = next((i + 1 for i, (uid, _) in enumerate(all_sorted) if uid == str(target.id)), "?")

    try: av_bytes = await target.display_avatar.with_size(256).read()
    except (discord.HTTPException, discord.Forbidden): av_bytes = None

    try:
        card_file = _make_rank_card(display_name=target.display_name, username=str(target), avatar_bytes=av_bytes, tier=ct, tier_title=title, total_xp=balance, xp_into=into, xp_needed=needed, rank_pos=position, balance=balance, theme=SAYORIES_THEME, filename="rank_card.png")
        await interaction.followup.send(file=card_file)
    except Exception:
        bar = progress_bar(into, needed)
        embed = (EmbedBuilder(color=color).title(f"{emoji} {target.display_name}'s Tier Profile").thumbnail(target.display_avatar.url).fields(("🏅 Tier", f"**Tier {ct}** — {title}" if ct > 0 else "Unranked"), ("🌍 Global Rank", f"#{position}"), ("🪙 Sayories", f"{balance:,} Sayories")).build())
        if ct < 25:
            embed.add_field(name=f"⬆️ Next: Tier {ct + 1} — {TIER_TITLES.get(ct + 1, '')}", value=f"{bar}\n`{into:,}` / `{needed:,}` Sayories to next tier", inline=False)
        else:
            embed.add_field(name="👑 Status", value="**MAX TIER — Sayorie Legend!** 💠", inline=False)
        await interaction.followup.send(embed=embed)

@tree.command(name="leaderboard", description="Show the top 10 members by Sayories/Tier globally")
async def leaderboard(interaction: discord.Interaction) -> None:
    if not await dm_check(interaction): return
    eco_data = await global_get_section("economy")
    if not eco_data: await interaction.response.send_message("No data yet!"); return
    top = sorted(eco_data.items(), key=lambda x: x[1].get("balance", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, d) in enumerate(top, 1):
        m = interaction.guild.get_member(int(uid)) if interaction.guild else None
        name = m.display_name if m else f"User {uid}"
        bal = d.get("balance", 0)
        ct = tier_from_xp(bal)
        emoji = TIER_EMOJIS.get(ct, "🌱")
        title = TIER_TITLES.get(ct, "Unranked")
        rank_icon = medals[i - 1] if i <= 3 else f"`{i}.`"
        lines.append(f"{rank_icon} **{name}** — {emoji} Tier {ct} *{title}* • `{bal:,}` 🪙")
    embed = (EmbedBuilder(color=Palette.SAYORIES).title("🏆 Global Tier Leaderboard").description("*The mightiest Barm members across all servers!*\n\n" + "\n".join(lines)).footer("Barm assistant • Global Leaderboard • Earn Sayories by chatting, working & VC!").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="tiers", description="Show the full Tier 1–25 progression chart")
async def tiers(interaction: discord.Interaction) -> None:
    if not await dm_check(interaction): return
    lines = []
    for t in range(1, 26):
        req = sayories_threshold_for_tier(t)
        emoji = TIER_EMOJIS[t]
        title = TIER_TITLES[t]
        lines.append(f"{emoji} **Tier {t}** — *{title}* • `{req:,}` 🪙")
        if t % 5 == 0 and t < 25: lines.append("─────────────────────────")
    half = len(lines) // 2
    embed = (EmbedBuilder(color=Palette.PRIMARY).title("📊 Tier Progression Chart — Tier 1 to 25").description("*Your Sayories balance determines your Tier. Earn by chatting, working, daily rewards & VC!*").field("Tiers 1–13", "\n".join(lines[:half])).field("Tiers 14–25", "\n".join(lines[half:])).footer("Create Discord roles named 'Level 1', 'Level 2'... for auto-assignment!").build())
    await interaction.response.send_message(embed=embed)

# (Omitted for brevity: Stars, Topquoter, Make it a Quote, Trackword, Untrackword, Wordcount, Trackedwords, 8ball, Battle, Choose, Coinflip, Dice, Race, TruthOrDare, IceCream commands. They use EmbedBuilder directly as per previous file.)
@tree.command(name="bocchi_rank", description="🔥 View your or another member's Bocchies tier in this server")
@app_commands.describe(member="Member to check (defaults to you)")
async def bocchi_rank_cmd(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    if not await guild_check(interaction): return
    await interaction.response.defer()
    target = member or interaction.user
    points = await bocchi_get(interaction.guild_id, target.id)
    rank = bocchi_rank_from_points(points)
    cr, into, needed = bocchi_progress(points)

    n_emoji = BOCCHI_RANK_EMOJIS.get(rank, "🔥") if rank > 0 else "🥚"
    n_title = BOCCHI_RANK_TITLES.get(rank, "Unranked") if rank > 0 else "Unranked"
    n_color = BOCCHI_RANK_COLORS.get(rank, 0xFF4500)

    all_data = await bocchi_get_all(interaction.guild_id)
    sorted_ids = sorted(all_data, key=lambda u: all_data[u].get("points", 0), reverse=True)
    pos = next((i + 1 for i, uid in enumerate(sorted_ids) if uid == str(target.id)), "?")

    try: av_bytes = await target.display_avatar.with_size(256).read()
    except (discord.HTTPException, discord.Forbidden): av_bytes = None

    try:
        card_file = _make_rank_card(display_name=target.display_name, username=str(target), avatar_bytes=av_bytes, tier=rank, tier_title=n_title, total_xp=points, xp_into=into, xp_needed=needed, rank_pos=pos, balance=points, theme=BOCCHI_THEME, filename="bocchi_tier_card.png")
        await interaction.followup.send(file=card_file)
    except Exception:
        bar = progress_bar(into, needed) if needed > 0 else ("█" * 16 + " MAX")
        embed = (EmbedBuilder(color=n_color).title(f"🔥 Bocchies Tier — {target.display_name}").thumbnail(target.display_avatar.url).fields(("Tier", f"{n_emoji} **Tier {rank}** — {n_title}" if rank > 0 else "🥚 Unranked"), ("Bocchies", f"`{points:,}` 🔥"), ("Position", f"**#{pos}** in this server")).build())
        if needed > 0:
            embed.add_field(name="Progress to next tier", value=f"{bar}\n`{into:,}` / `{needed:,}` ({needed - into:,} to go)", inline=False)
        else:
            embed.add_field(name="Progress", value="🏆 **MAX TIER — Bocchi Legend!**", inline=False)
        embed.set_footer(text=f"Barm assistant 🔥 Bocchies • {interaction.guild.name} only")
        await interaction.followup.send(embed=embed)


install_error_handler(tree)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    join_to_create_id = await db_get(member.guild.id, "join_to_create_vc")
    if not join_to_create_id: return

    if after.channel and after.channel.id == join_to_create_id:
        try:
            temp_ch = await member.guild.create_voice_channel(name=f"🔊 {member.display_name}'s VC", category=after.channel.category, reason="Temp VC auto-created")
            await member.move_to(temp_ch)
            temp_vcs = await db_get_section(member.guild.id, "temp_vcs")
            temp_vcs[str(temp_ch.id)] = member.id
            await db_save_section(member.guild.id, "temp_vcs", temp_vcs)
        except Exception as e: print(f"[TempVC] Could not create channel: {e}")

    if before.channel and before.channel.id != join_to_create_id:
        temp_vcs = await db_get_section(member.guild.id, "temp_vcs")
        if str(before.channel.id) in temp_vcs and len(before.channel.members) == 0:
            try:
                await before.channel.delete(reason="Temp VC empty — auto-deleted")
                temp_vcs.pop(str(before.channel.id))
                await db_save_section(member.guild.id, "temp_vcs", temp_vcs)
            except Exception as e: print(f"[TempVC] Could not delete channel: {e}")

@tree.command(name="balance", description="Check your or another member's Sayories balance")
@app_commands.describe(member="Member to check (leave blank for yourself)")
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    if not await dm_check(interaction): return
    target = member or interaction.user
    bal = await g_eco_get(target.id)
    embed = (EmbedBuilder(color=Palette.SAYORIES).title(f"🪙 {target.display_name}'s Wallet").thumbnail(target.display_avatar.url).fields(("💰 Balance", f"**{bal:,} Sayories**"), ("🌍 Scope", "Global (all servers)")).footer("Barm assistant Economy • Global Balance").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="daily", description="Claim your daily 200 Sayories")
async def daily(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    uid = str(interaction.user.id)
    now = time.time()
    async with _global_lock:
        gdata = _load_global()
        eco = gdata.setdefault("economy", {})
        eco.setdefault(uid, {})
        last = eco[uid].get("last_daily", 0)
        if now - last < 86400:
            rem = int(86400 - (now - last)); h, m = divmod(rem // 60, 60)
            embed = (EmbedBuilder(color=Palette.DANGER).title("⏳ Daily Already Claimed").description(f"Come back in **{h}h {m}m** for your next daily reward!").footer("Barm assistant Economy").build())
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        eco[uid]["balance"] = eco[uid].get("balance", 0) + 200
        eco[uid]["last_daily"] = now
        new_bal = eco[uid]["balance"]
        old_tier = tier_from_xp(new_bal - 200)
        new_tier = tier_from_xp(new_bal)
        _save_global(gdata)
    if interaction.guild and new_tier > old_tier and new_tier >= 1: await assign_tier_role(interaction.user, new_tier)
    embed = (EmbedBuilder(color=Palette.SUCCESS).title("💰 Daily Reward Claimed!").description(f"{interaction.user.mention} collected their daily **200 Sayories**! 🎉").thumbnail(interaction.user.display_avatar.url).fields(("💵 Earned", "200 Sayories"), ("💰 New Balance", f"{new_bal:,} Sayories")).footer("Come back tomorrow for more! • Barm assistant Economy").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="work", description="Work to earn Sayories (1 hour cooldown)")
async def work(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    uid_str = str(interaction.user.id)
    key = interaction.user.id
    now = time.time()
    if now - bot._work_cd.get(key, 0) < 3600:
        rem = int(3600 - (now - bot._work_cd[key]))
        embed = (EmbedBuilder(color=Palette.WARNING).title("😴 You're Tired!").description(f"Rest up and work again in **{rem // 60}m {rem % 60}s**.").footer("Barm assistant Economy").build())
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    bot._work_cd[key] = now
    earned = random.randint(50, 150)
    jobs = [("🧹", "cleaned the city fountain"), ("📦", "delivered packages"), ("🐕", "walked dogs"), ("💻", "fixed computers"), ("🍳", "cooked meals at the café"), ("📚", "tutored students"), ("🚖", "drove a taxi"), ("⌨️", "wrote code"), ("🖌️", "painted fences"), ("🎸", "busked in the park"), ("🌿", "tended a garden"), ("📸", "photographed events")]
    emoji, job = random.choice(jobs)
    old_tier = 0; new_tier = 0; new_bal = 0
    async with _global_lock:
        gdata = _load_global()
        eco = gdata.setdefault("economy", {})
        eco.setdefault(uid_str, {})
        old_bal = eco[uid_str].get("balance", 0)
        old_tier = tier_from_xp(old_bal)
        new_bal = old_bal + earned
        new_tier = tier_from_xp(new_bal)
        eco[uid_str]["balance"] = new_bal
        _save_global(gdata)
    if interaction.guild and new_tier > old_tier and new_tier >= 1: await assign_tier_role(interaction.user, new_tier)
    embed = (EmbedBuilder(color=Palette.SUCCESS).title(f"{emoji} Work Complete!").description(f"**{interaction.user.display_name}** {job} and earned some Sayories!").thumbnail(interaction.user.display_avatar.url).fields(("💵 Earned", f"**{earned:,} Sayories**"), ("🏦 New Balance", f"**{new_bal:,} Sayories**")).footer("Barm assistant Economy • Global • Work cooldown: 1 hour").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="pay", description="Send Sayories to another member")
@app_commands.describe(member="Member to pay", amount="Amount of Sayories to send")
async def pay(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not await dm_check(interaction): return
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return
    if member.bot:
        await interaction.response.send_message("❌ You can't pay bots.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't pay yourself.", ephemeral=True)
        return

    sender_id = str(interaction.user.id)
    receiver_id = str(member.id)
    insufficient_bal: int | None = None
    new_sender_bal = 0
    new_receiver_bal = 0
    async with _global_lock:
        gdata = _load_global()
        eco = gdata.setdefault("economy", {})
        eco.setdefault(sender_id, {})
        eco.setdefault(receiver_id, {})
        sender_bal = eco[sender_id].get("balance", 0)
        if sender_bal < amount:
            insufficient_bal = sender_bal
        else:
            eco[sender_id]["balance"] = sender_bal - amount
            eco[receiver_id]["balance"] = eco[receiver_id].get("balance", 0) + amount
            new_sender_bal = eco[sender_id]["balance"]
            new_receiver_bal = eco[receiver_id]["balance"]
            _save_global(gdata)

    if insufficient_bal is not None:
        await interaction.response.send_message(f"❌ Not enough Sayories (you have {insufficient_bal:,}).", ephemeral=True)
        return

    embed = (EmbedBuilder(color=Palette.SAYORIES)
        .title("💸 Payment Sent")
        .description(f"{interaction.user.mention} sent **{amount:,} Sayories** to {member.mention}.")
        .fields(("Your Balance", f"`{new_sender_bal:,}`"), (f"{member.display_name}'s Balance", f"`{new_receiver_bal:,}`"))
        .branded("Economy").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="richest", description="Show the richest members by global Sayories")
async def richest(interaction: discord.Interaction):
    if not await dm_check(interaction): return
    eco = await global_get_section("economy")
    if not eco:
        await interaction.response.send_message("No economy data yet.")
        return
    top = sorted(eco.items(), key=lambda item: item[1].get("balance", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (uid, data) in enumerate(top, 1):
        member = interaction.guild.get_member(int(uid)) if interaction.guild else None
        name = member.display_name if member else f"User {uid}"
        badge = medals[idx - 1] if idx <= 3 else f"`{idx}.`"
        lines.append(f"{badge} **{name}** • `{data.get('balance', 0):,}` 🪙")
    embed = (EmbedBuilder(color=Palette.SAYORIES)
        .title("🏦 Richest Members")
        .description("\n".join(lines))
        .branded("Economy").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="setjoinvc", description="🔊 Set the Join-to-Create voice channel")
@app_commands.describe(channel="The voice channel users join to create their own")
@app_commands.checks.has_permissions(manage_guild=True)
async def setjoinvc(interaction: discord.Interaction, channel: discord.VoiceChannel):
    if not await guild_check(interaction): return
    await db_set(interaction.guild_id, channel.id, "join_to_create_vc")
    embed = (EmbedBuilder(color=Palette.SUCCESS).title("🔊 Join-to-Create VC Set").description(f"Users who join **{channel.name}** will automatically get their own temporary voice channel!\\n\\nThe temp VC is deleted when everyone leaves.").field("📢 Trigger Channel", channel.mention).footer("Barm assistant • Temp VC System").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="sync", description="🔧 [Owner only] Force re-sync all slash commands to Discord")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await safe_sync(bot)
    embed = (EmbedBuilder(color=Palette.SUCCESS).title("✅ Commands Synced").description("Global + guild command sync finished — check the console for counts.\nNote: Global commands can take up to an hour to appear in all servers.").footer("Barm assistant • Sync").build())
    await interaction.followup.send(embed=embed, ephemeral=True)

@tree.command(name="help", description="Show all General bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("general", "Core economy, admin utilities, temp voice channels, and ADO Den Haag news.", {"💰 Economy": ["`/balance [member]`", "`/daily`", "`/work`", "`/pay <member> <amount>`", "`/richest`"], "🔊 Voice": ["`/setjoinvc <channel>` — Join-to-Create temp VC (admin)"], "🔧 Owner-only": ["`/sync`"]})
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("GENERAL_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the GENERAL_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
