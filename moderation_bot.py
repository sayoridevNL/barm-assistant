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


# ─────────────────────────────  Custom Features  ─────────────────────────────
CUSTOM_GUILD_ID = 1049396166250475612
SUGGESTION_CHANNEL_ID = 1171457664136532010
SERVER_OWNER_ID = 879118301169602570
TARGET_USERS = {1158703899843231836, 315845909533556741}

from ui_kit import CooldownMap
suggestion_cooldowns = CooldownMap(3600)

class SuggestionView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=None)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        app_info = await bot.application_info()
        if interaction.user.id not in (app_info.owner.id, SERVER_OWNER_ID):
            await interaction.response.send_message("❌ You are not authorized to accept or reject suggestions.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="sugg_acc")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("✅ Suggestion accepted. Creating poll...", ephemeral=True)
        self.stop()
        
        # Edit original message to remove buttons and show accepted
        embed = interaction.message.embeds[0]
        embed.color = Palette.SUCCESS
        embed.title = "✅ Accepted Suggestion"
        await interaction.message.edit(embed=embed, view=None)

        # Create the poll with emojis
        poll_msg = await interaction.channel.send(content="**Suggestion Poll:** (Active for 24 hours)", embed=embed)
        await poll_msg.add_reaction("👍")
        await poll_msg.add_reaction("👎")

        # Track poll
        await db_set(interaction.guild_id, self.author_id, f"poll_{poll_msg.id}")
        
        # Setup 24h deletion task
        async def close_poll():
            await asyncio.sleep(86400)
            try:
                msg = await interaction.channel.fetch_message(poll_msg.id)
                await msg.reply("This poll has concluded.")
            except:
                pass
        bot.loop.create_task(close_poll())

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="sugg_rej")
    async def btn_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Suggestion rejected.", ephemeral=True)
        self.stop()
        embed = interaction.message.embeds[0]
        embed.color = Palette.ERROR
        embed.title = "❌ Rejected Suggestion"
        await interaction.message.edit(embed=embed, view=None)


@tree.command(name="suggest", description="Make a suggestion for the server (1 hour cooldown)")
@app_commands.describe(suggestion="Your suggestion")
async def custom_suggest(interaction: discord.Interaction, suggestion: str):
    if interaction.guild_id != CUSTOM_GUILD_ID:
        return await interaction.response.send_message("❌ This command is not available in this server.", ephemeral=True)
    
    if suggestion_cooldowns.update(interaction.user.id):
        rem = suggestion_cooldowns.get_remaining(interaction.user.id)
        return await interaction.response.send_message(f"⏳ You are on cooldown. Try again in {int(rem/60)} minutes.", ephemeral=True)

    sugg_channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
    if not sugg_channel:
        return await interaction.response.send_message("❌ Suggestion channel not found.", ephemeral=True)

    embed = (EmbedBuilder(color=Palette.INFO)
             .title("💡 New Suggestion")
             .description(suggestion)
             .footer(f"Suggested by {interaction.user}")
             .build())
             
    view = SuggestionView(interaction.user.id)
    await sugg_channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Suggestion submitted!", ephemeral=True)


@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild and message.guild.id == CUSTOM_GUILD_ID:
        author_id = await db_get(message.guild.id, f"poll_{message.id}")
        if author_id or (message.embeds and ("New Suggestion" in str(message.embeds[0].title) or "Accepted Suggestion" in str(message.embeds[0].title))):
            # Give audit log a moment to populate
            await asyncio.sleep(2)
            async for entry in message.guild.audit_logs(action=discord.AuditLogAction.message_delete, limit=5):
                if entry.target.id == message.author.id:
                    # Notify bot owner / server owner
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
