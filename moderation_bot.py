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


# ─────────────────────────────  LOGGING & EVENTS  ─────────────────────────────
DEFAULT_DM_RECIPIENTS = [787681263267479572, 1043235209639886972, 879118301169602570]

async def dispatch_log(guild: discord.Guild, embed: discord.Embed, is_vc: bool = False):
    # 1. Send to configured log channel
    cid = await db_get(guild.id, "log_channel")
    if cid:
        ch = guild.get_channel(cid)
        if ch:
            try: await ch.send(embed=embed)
            except: pass

    # 2. Send to configured DMs ONLY for the specific server (1049396166250475612) and not for VC logs
    if not is_vc and guild.id == 1049396166250475612:
        dm_users = await db_get(guild.id, "log_dms", default=DEFAULT_DM_RECIPIENTS)
        for uid in dm_users:
            try:
                user = guild.get_member(uid) or await bot.fetch_user(uid)
                if user:
                    await user.send(f"**Log for {guild.name}**", embed=embed)
            except: pass

@tree.command(name="log_dm", description="Manage who receives moderation logs in their DMs")
@app_commands.describe(action="Add or remove", user="The user to modify")
@app_commands.choices(action=[
    app_commands.Choice(name="add", value="add"),
    app_commands.Choice(name="remove", value="remove")
])
async def log_dm_cmd(interaction: discord.Interaction, action: str, user: discord.User):
    if interaction.user.id != BOT_OWNER_ID and interaction.user.id != 879118301169602570:
        return await interaction.response.send_message("❌ Only the bot owner can manage DM logs.", ephemeral=True)
    if not await guild_check(interaction): return
    current = await db_get(interaction.guild_id, "log_dms", default=DEFAULT_DM_RECIPIENTS.copy())
    
    if action == "add":
        if user.id not in current:
            current.append(user.id)
            msg = f"✅ Added {user.mention} to DM logs."
        else:
            msg = f"⚠️ {user.mention} is already in the DM logs list."
    else:
        if user.id in current:
            current.remove(user.id)
            msg = f"✅ Removed {user.mention} from DM logs."
        else:
            msg = f"⚠️ {user.mention} is not in the DM logs list."
            
    await db_set(interaction.guild_id, current, "log_dms")
    await interaction.response.send_message(msg, ephemeral=True)

# Helper to fetch audit log actor
async def get_actor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None) -> discord.User | None:
    import asyncio
    await asyncio.sleep(1) # Wait for audit log to populate
    try:
        async for entry in guild.audit_logs(action=action, limit=5):
            if target_id is None or (entry.target and getattr(entry.target, "id", None) == target_id):
                return entry.user
    except: pass
    return None

@bot.event
async def on_message_delete(message: discord.Message):
    if not message.guild or message.author.bot: return
    
    actor = await get_actor(message.guild, discord.AuditLogAction.message_delete, message.author.id)
    actor_str = f"{actor.mention}" if actor else f"{message.author.mention} (Self/Unknown)"
    
    desc = f"**Message deleted in {message.channel.mention}**\n"
    if message.content: desc += f"**Content:** {message.content[:1000]}\n"
    
    embed = EmbedBuilder(color=Palette.DANGER).title("🗑️ Message Deleted").description(desc).fields(("👤 Author", f"{message.author.mention} (`{message.author.id}`)"), ("🛡️ Deleted By", actor_str)).footer("Barm assistant Logging").build()
    
    # Attach images if any
    if message.attachments:
        att = message.attachments[0]
        if any(att.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
            embed.set_image(url=att.proxy_url)
            embed.add_field(name="📎 Attachment", value=att.filename, inline=False)
            
    await dispatch_log(message.guild, embed)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not before.guild or before.author.bot or before.content == after.content: return
    desc = f"**Message edited in {before.channel.mention}** [Jump]({after.jump_url})\n\n**Before:** {before.content[:500]}\n**After:** {after.content[:500]}"
    embed = EmbedBuilder(color=Palette.WARNING).title("✏️ Message Edited").description(desc).fields(("👤 Author", f"{before.author.mention} (`{before.author.id}`)"),).footer("Barm assistant Logging").build()
    await dispatch_log(before.guild, embed)

@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    actor = await get_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
    embed = EmbedBuilder(color=Palette.SUCCESS).title("📁 Channel Created").description(f"Channel {channel.mention} (`{channel.name}`) was created.").fields(("🛡️ Created By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
    await dispatch_log(channel.guild, embed)

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    actor = await get_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
    embed = EmbedBuilder(color=Palette.DANGER).title("📁 Channel Deleted").description(f"Channel `# {channel.name}` was deleted.").fields(("🛡️ Deleted By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
    await dispatch_log(channel.guild, embed)

@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
    if before.name == after.name and before.category == after.category: return
    actor = await get_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
    embed = EmbedBuilder(color=Palette.WARNING).title("📁 Channel Updated").description(f"Channel {after.mention} was updated.\n**Name:** {before.name} -> {after.name}").fields(("🛡️ Updated By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
    await dispatch_log(after.guild, embed)

@bot.event
async def on_guild_role_create(role: discord.Role):
    actor = await get_actor(role.guild, discord.AuditLogAction.role_create, role.id)
    embed = EmbedBuilder(color=Palette.SUCCESS).title("🏷️ Role Created").description(f"Role {role.mention} was created.").fields(("🛡️ Created By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
    await dispatch_log(role.guild, embed)

@bot.event
async def on_guild_role_delete(role: discord.Role):
    actor = await get_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
    embed = EmbedBuilder(color=Palette.DANGER).title("🏷️ Role Deleted").description(f"Role `@{role.name}` was deleted.").fields(("🛡️ Deleted By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
    await dispatch_log(role.guild, embed)

@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    if before.name == after.name and before.color == after.color and before.permissions == after.permissions: return
    actor = await get_actor(after.guild, discord.AuditLogAction.role_update, after.id)
    embed = EmbedBuilder(color=Palette.WARNING).title("🏷️ Role Updated").description(f"Role {after.mention} was updated.").fields(("🛡️ Updated By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
    await dispatch_log(after.guild, embed)

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # Nickname
    if before.nick != after.nick:
        actor = await get_actor(after.guild, discord.AuditLogAction.member_update, after.id)
        embed = EmbedBuilder(color=Palette.WARNING).title("👤 Nickname Changed").description(f"**{after.mention}** nickname changed.\n**Before:** {before.nick}\n**After:** {after.nick}").fields(("🛡️ Changed By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
        await dispatch_log(after.guild, embed)
        
    # Roles
    if before.roles != after.roles:
        added = [r.mention for r in after.roles if r not in before.roles]
        removed = [r.mention for r in before.roles if r not in after.roles]
        if added or removed:
            actor = await get_actor(after.guild, discord.AuditLogAction.member_role_update, after.id)
            desc = f"**{after.mention}** roles updated.\n"
            if added: desc += f"**Added:** {', '.join(added)}\n"
            if removed: desc += f"**Removed:** {', '.join(removed)}\n"
            embed = EmbedBuilder(color=Palette.WARNING).title("🏷️ Member Roles Updated").description(desc).fields(("🛡️ Updated By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
            await dispatch_log(after.guild, embed)
            
    # Timeout
    if before.is_timed_out() != after.is_timed_out():
        actor = await get_actor(after.guild, discord.AuditLogAction.member_update, after.id)
        if after.is_timed_out():
            embed = EmbedBuilder(color=Palette.DANGER).title("⏳ Member Timed Out").description(f"**{after.mention}** was timed out until {after.timed_out_until}.").fields(("🛡️ Timed Out By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
        else:
            embed = EmbedBuilder(color=Palette.SUCCESS).title("✅ Timeout Removed").description(f"**{after.mention}** timeout was removed.").fields(("🛡️ Removed By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
        await dispatch_log(after.guild, embed)

@bot.event
async def on_user_update(before: discord.User, after: discord.User):
    if before.name != after.name or before.discriminator != after.discriminator:
        for guild in bot.guilds:
            if guild.get_member(after.id):
                embed = EmbedBuilder(color=Palette.WARNING).title("👤 Username Changed").description(f"**{after.mention}** changed their username.\n**Before:** {before.name}#{before.discriminator}\n**After:** {after.name}#{after.discriminator}").footer("Barm assistant Logging").build()
                await dispatch_log(guild, embed)
                break

@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    if before.name != after.name:
        actor = await get_actor(after, discord.AuditLogAction.guild_update)
        embed = EmbedBuilder(color=Palette.WARNING).title("🏠 Server Name Changed").description(f"**Before:** {before.name}\n**After:** {after.name}").fields(("🛡️ Changed By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
        await dispatch_log(after, embed)
    if before.icon != after.icon:
        actor = await get_actor(after, discord.AuditLogAction.guild_update)
        embed = EmbedBuilder(color=Palette.WARNING).title("🏠 Server Icon Changed").description("The server icon was updated.").fields(("🛡️ Changed By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
        if after.icon: embed.set_image(url=after.icon.url)
        await dispatch_log(after, embed)

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    actor = await get_actor(guild, discord.AuditLogAction.ban, user.id)
    embed = EmbedBuilder(color=Palette.DANGER).title("🔨 Member Banned").description(f"**{user.mention}** (`{user.id}`) was banned.").fields(("🛡️ Banned By", actor.mention if actor else "Unknown")).footer("Barm assistant Logging").build()
    await dispatch_log(guild, embed)

@bot.event
async def on_member_remove(member: discord.Member):
    actor = await get_actor(member.guild, discord.AuditLogAction.kick, member.id)
    if actor:
        embed = EmbedBuilder(color=Palette.WARNING).title("👢 Member Kicked").description(f"**{member.mention}** (`{member.id}`) was kicked.").fields(("🛡️ Kicked By", actor.mention)).footer("Barm assistant Logging").build()
    else:
        embed = EmbedBuilder(color=Palette.DIM).title("👋 Member Left").description(f"**{member.mention}** (`{member.id}`) left the server.").footer("Barm assistant Logging").build()
    await dispatch_log(member.guild, embed)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel == after.channel: return
    if not before.channel and after.channel:
        embed = EmbedBuilder(color=Palette.SUCCESS).title("🔊 Joined Voice").description(f"**{member.mention}** joined {after.channel.mention}").footer("Barm assistant Logging").build()
    elif before.channel and not after.channel:
        embed = EmbedBuilder(color=Palette.DANGER).title("🔊 Left Voice").description(f"**{member.mention}** left {before.channel.mention}").footer("Barm assistant Logging").build()
    else:
        embed = EmbedBuilder(color=Palette.WARNING).title("🔊 Moved Voice").description(f"**{member.mention}** moved from {before.channel.mention} to {after.channel.mention}").footer("Barm assistant Logging").build()
    await dispatch_log(member.guild, embed, is_vc=True)

if __name__ == "__main__":
    TOKEN = os.getenv("MODERATION_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the MODERATION_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
