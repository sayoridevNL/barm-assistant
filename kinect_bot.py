"""
channel_linker_bot.py

Mirrors messages between two linked channels (possibly in different guilds)
using webhooks, preserving the original author's display name and avatar.
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from dotenv import load_dotenv

from shared import _get_mongo_db

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kinect")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

WEBHOOK_NAME_TAG = "kinect"

# In-memory caches so we don't hit MongoDB or the Discord API for every message.
link_cache = {}      # channel_id (str) -> {"target_channel_id": str, "target_guild_id": str} or None
webhook_cache = {}    # channel_id (str) -> discord.Webhook


def get_links_collection():
    db = _get_mongo_db()
    if db is not None:
        return db["channel_links"]
    return None

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def get_link_for_channel(channel_id: str):
    if channel_id in link_cache:
        return link_cache[channel_id]
        
    collection = get_links_collection()
    if collection is None:
        return None

    doc = await collection.find_one(
        {"$or": [{"channel_id_1": channel_id}, {"channel_id_2": channel_id}]}
    )

    if doc is None:
        link_cache[channel_id] = None
        return None

    is_first = doc["channel_id_1"] == channel_id
    link = {
        "target_channel_id": doc["channel_id_2"] if is_first else doc["channel_id_1"],
        "target_guild_id": doc["guild_id_2"] if is_first else doc["guild_id_1"],
    }

    link_cache[channel_id] = link
    return link


async def is_channel_already_linked(channel_id: str) -> bool:
    collection = get_links_collection()
    if collection is None:
        return False
    doc = await collection.find_one(
        {"$or": [{"channel_id_1": channel_id}, {"channel_id_2": channel_id}]}
    )
    return doc is not None


async def save_link(channel1: str, guild1: str, channel2: str, guild2: str, created_by: str):
    collection = get_links_collection()
    if collection is None:
        return
        
    await collection.insert_one(
        {
            "channel_id_1": channel1,
            "guild_id_1": guild1,
            "channel_id_2": channel2,
            "guild_id_2": guild2,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc),
        }
    )

    # Invalidate cache entries for both channels so the new link is picked up.
    link_cache.pop(channel1, None)
    link_cache.pop(channel2, None)


# ---------------------------------------------------------------------------
# Webhook helpers
# ---------------------------------------------------------------------------

async def get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook:
    channel_id = str(channel.id)

    if channel_id in webhook_cache:
        return webhook_cache[channel_id]

    existing_webhooks = await channel.webhooks()
    webhook = discord.utils.get(existing_webhooks, name=WEBHOOK_NAME_TAG)

    if webhook is None:
        webhook = await channel.create_webhook(
            name=WEBHOOK_NAME_TAG,
            reason="Created for cross-server channel linking",
        )

    webhook_cache[channel_id] = webhook
    return webhook


# ---------------------------------------------------------------------------
# Message mirroring
# ---------------------------------------------------------------------------

@bot.event
async def on_message(message: discord.Message):
    try:
        # Ignore bots (including ourselves and our own webhook messages) to avoid loops.
        if message.author.bot:
            return
        if message.guild is None:
            return

        link = await get_link_for_channel(str(message.channel.id))
        if link is None:
            return

        target_guild = bot.get_guild(int(link["target_guild_id"]))
        if target_guild is None:
            logger.error("Target guild %s not found in cache.", link["target_guild_id"])
            return

        target_channel = target_guild.get_channel(int(link["target_channel_id"]))
        if target_channel is None:
            try:
                target_channel = await target_guild.fetch_channel(int(link["target_channel_id"]))
            except discord.NotFound:
                target_channel = None

        if not isinstance(target_channel, discord.TextChannel):
            logger.error("Target channel %s not found or not a text channel.", link["target_channel_id"])
            return

        webhook = await get_or_create_webhook(target_channel)

        display_name = message.author.display_name
        avatar_url = message.author.display_avatar.url
        source_guild_name = message.guild.name
        webhook_username = f"{display_name} (via {source_guild_name})"[:80]  # discord username limit

        files = [await a.to_file() for a in message.attachments] if message.attachments else []

        await webhook.send(
            content=message.content or None,
            username=webhook_username,
            avatar_url=avatar_url,
            files=files,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except Exception:
        logger.exception("Failed to mirror message %s", message.id)


# ---------------------------------------------------------------------------
# /link slash command
# ---------------------------------------------------------------------------

@tree.command(name="link", description="Link this channel to a channel in another server so messages mirror between them.")
@app_commands.describe(channel1="First channel ID", channel2="Second channel ID")
async def link_command(interaction: discord.Interaction, channel1: str, channel2: str):
    await interaction.response.defer(ephemeral=True)

    member = interaction.user
    is_admin = member.guild_permissions.administrator
    is_owner = interaction.guild.owner_id == member.id

    if not is_admin and not is_owner:
        await interaction.followup.send(
            "You need Administrator permission or to be the server owner to use this command."
        )
        return

    try:
        ch1 = bot.get_channel(int(channel1)) or await bot.fetch_channel(int(channel1))
        ch2 = bot.get_channel(int(channel2)) or await bot.fetch_channel(int(channel2))
    except (discord.NotFound, ValueError):
        await interaction.followup.send("One of those channel IDs is invalid.")
        return

    if not isinstance(ch1, discord.TextChannel):
        await interaction.followup.send(f"Channel {channel1} was not found or is not a text channel.")
        return
    if not isinstance(ch2, discord.TextChannel):
        await interaction.followup.send(f"Channel {channel2} was not found or is not a text channel.")
        return

    bot_member_1 = ch1.guild.me
    bot_member_2 = ch2.guild.me

    if not ch1.permissions_for(bot_member_1).manage_webhooks:
        await interaction.followup.send(f"I don't have permission to manage webhooks in <#{channel1}>.")
        return
    if not ch2.permissions_for(bot_member_2).manage_webhooks:
        await interaction.followup.send(f"I don't have permission to manage webhooks in <#{channel2}>.")
        return

    if await is_channel_already_linked(channel1) or await is_channel_already_linked(channel2):
        await interaction.followup.send("One of these channels is already linked to another channel.")
        return

    await save_link(channel1, str(ch1.guild.id), channel2, str(ch2.guild.id), str(member.id))

    await interaction.followup.send(
        f"Linked <#{channel1}> ({ch1.guild.name}) with <#{channel2}> ({ch2.guild.name}). "
        f"Messages will now mirror between them."
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    logger.info("Logged in as %s", bot.user)
    
    collection = get_links_collection()
    if collection is not None:
        await collection.create_index([("channel_id_1", 1)], unique=True)
        await collection.create_index([("channel_id_2", 1)], unique=True)
        logger.info("Channel links MongoDB indexes verified.")

    # Sync the /link command to every guild the bot is currently in.
    for guild in bot.guilds:
        try:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        except Exception:
            logger.exception("Failed to sync /link in guild %s", guild.id)