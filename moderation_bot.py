from __future__ import annotations
import os
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from shared import *
from theme import EmbedBuilder, Palette
from ui_kit import install_error_handler

class ModerationBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="§unused-mod§", intents=intents, help_command=None)

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        cid = await db_get(guild.id, "log_channel")
        if cid:
            ch = guild.get_channel(cid)
            if ch:
                try: await ch.send(embed=embed)
                except Exception: pass

    async def on_ready(self):
        print("🔄 Syncing moderation bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("moderation", self)
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["moderation"]["status"]))

bot = ModerationBot()
tree = bot.tree
install_error_handler(tree)

@bot.event
async def on_guild_join(guild: discord.Guild):
    if await sync_guild_safely(bot, guild): print(f"✅ Synced commands to new guild: {guild.name}")
    else: print(f"⚠️  Failed to sync to {guild.name}")

@tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Member to ban", reason="Reason for the ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await guild_check(interaction): return
    await member.ban(reason=reason)
    embed = (EmbedBuilder(color=Palette.DANGER).title("🔨 Member Banned").description(f"**{member}** has been banned from the server.").thumbnail(member.display_avatar.url).fields(("👤 User", f"{member.mention} (`{member.id}`)"), ("🛡️ Moderator", interaction.user.mention), ("📝 Reason", reason)).footer("Barm assistant Moderation").build())
    await interaction.response.send_message(embed=embed)
    await bot.send_log(interaction.guild, embed)

@tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Member to kick", reason="Reason")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await guild_check(interaction): return
    await member.kick(reason=reason)
    embed = (EmbedBuilder(color=Palette.WARNING).title("👢 Member Kicked").description(f"**{member}** has been kicked from the server.").thumbnail(member.display_avatar.url).fields(("👤 User", f"{member.mention} (`{member.id}`)"), ("🛡️ Moderator", interaction.user.mention), ("📝 Reason", reason)).footer("Barm assistant Moderation").build())
    await interaction.response.send_message(embed=embed)
    await bot.send_log(interaction.guild, embed)

@tree.command(name="timeout", description="Timeout a member for a number of minutes")
@app_commands.describe(member="Member to timeout", minutes="Duration in minutes (max 40320 / 28 days)", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout_member(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
    if not await guild_check(interaction): return
    if minutes <= 0 or minutes > 40320:
        await interaction.response.send_message("❌ Timeout minutes must be between 1 and 40,320 (28 days).", ephemeral=True)
        return
    until = discord.utils.utcnow() + timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    embed = (EmbedBuilder(color=Palette.WARNING)
        .title("⏳ Member Timed Out")
        .description(f"**{member}** has been timed out for **{minutes:,} minute(s)**.")
        .thumbnail(member.display_avatar.url)
        .fields(("👤 User", f"{member.mention} (`{member.id}`)"), ("🛡️ Moderator", interaction.user.mention), ("📝 Reason", reason))
        .footer("Barm assistant Moderation").build())
    await interaction.response.send_message(embed=embed)
    await bot.send_log(interaction.guild, embed)

@tree.command(name="untimeout", description="Remove a member timeout")
@app_commands.describe(member="Member to remove timeout from", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout_member(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await guild_check(interaction): return
    await member.timeout(None, reason=reason)
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title("✅ Timeout Removed")
        .description(f"**{member}** can talk again.")
        .thumbnail(member.display_avatar.url)
        .fields(("👤 User", f"{member.mention} (`{member.id}`)"), ("🛡️ Moderator", interaction.user.mention), ("📝 Reason", reason))
        .footer("Barm assistant Moderation").build())
    await interaction.response.send_message(embed=embed)
    await bot.send_log(interaction.guild, embed)

@tree.command(name="setlog", description="Set the channel for bot logs")
@app_commands.describe(channel="The channel to send logs to (leave blank for current)")
@app_commands.checks.has_permissions(manage_guild=True)
async def setlog(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not await guild_check(interaction): return
    ch = channel or interaction.channel
    await db_set(interaction.guild_id, ch.id, "log_channel")
    embed = (EmbedBuilder(color=Palette.SUCCESS).title("📋 Log Channel Set").description(f"All server logs will now be sent to {ch.mention}.").fields(("📢 Channel", ch.mention), ("🆔 Channel ID", str(ch.id))).footer(f"Set by {interaction.user} • Barm assistant").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="help", description="Show all Moderation bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("moderation", "Member actions and the server audit log. Use `/setlog` first so log embeds go somewhere.", {"🔨 Actions": ["`/ban <member> [reason]`", "`/kick <member> [reason]`", "`/timeout <member> <minutes> [reason]`", "`/untimeout <member> [reason]`"], "📋 Setup": ["`/setlog [channel]` — set where audit-log embeds are posted"]})
    await interaction.response.send_message(embed=embed)




# ─────────────────────────────  Custom Audit Logging  ─────────────────────────────
CUSTOM_GUILD_ID = 1049396166250475612
SERVER_OWNER_ID = 879118301169602570
TARGET_USERS = {1158703899843231836, 315845909533556741}

@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild and message.guild.id == CUSTOM_GUILD_ID:
        author_id = await db_get(message.guild.id, f"poll_{message.id}")
        if author_id or (message.embeds and ("New Suggestion" in str(message.embeds[0].title) or "Accepted Suggestion" in str(message.embeds[0].title))):
            import asyncio
            await asyncio.sleep(2)
            async for entry in message.guild.audit_logs(action=discord.AuditLogAction.message_delete, limit=5):
                if entry.target.id == message.author.id:
                    app_info = await bot.application_info()
                    bot_owner = app_info.owner
                    srv_owner = message.guild.get_member(SERVER_OWNER_ID) or await bot.fetch_user(SERVER_OWNER_ID)
                    
                    notify_msg = f"⚠️ Suggestion/Poll deleted by admin **{entry.user}** in {message.channel.mention}."
                    
                    try: await bot_owner.send(notify_msg)
                    except: pass
                    
                    if srv_owner:
                        try: await srv_owner.send(notify_msg)
                        except: pass
                    
                    if author_id:
                        suggester = message.guild.get_member(author_id) or await bot.fetch_user(author_id)
                        if suggester:
                            try: await suggester.send(f"Your suggestion poll was deleted by admin **{entry.user}**.")
                            except: pass
                    break

@bot.event
async def on_message(message: discord.Message):
    if message.author.id in TARGET_USERS and "timeout" in message.content.lower():
        app_info = await bot.application_info()
        try:
            await app_info.owner.send(f"🔔 Target user **{message.author}** said 'timeout':\n> {message.content}\nURL: {message.jump_url}")
        except: pass


@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    if entry.guild.id != CUSTOM_GUILD_ID: return
    
    is_target_actor = entry.user.id in TARGET_USERS
    is_target_target = getattr(entry.target, "id", None) in TARGET_USERS
    
    if is_target_actor or is_target_target:
        app_info = await bot.application_info()
        action_name = str(entry.action).replace("AuditLogAction.", "")
        target_name = str(entry.target) if entry.target else "Unknown"
        
        msg = f"📝 **Audit Log Alert**\n**Action**: `{action_name}`\n**Actor**: {entry.user} (`{entry.user.id}`)\n**Target**: {target_name}"
        if entry.reason:
            msg += f"\n**Reason**: {entry.reason}"
        if entry.extra:
            msg += f"\n**Extra**: {entry.extra}"
            
        try:
            await app_info.owner.send(msg)
        except: pass

if __name__ == "__main__":
    TOKEN = os.getenv("MODERATION_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the MODERATION_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
