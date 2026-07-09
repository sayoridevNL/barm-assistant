from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional as _Optional

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from shared import *
from theme import EmbedBuilder, Palette
from ui_kit import ask_confirm, install_error_handler

SPOTIFY_DB_FILE = "spotify_stats.json"
SPOTIFY_PER_PAGE = 15
spotify_db_data: dict = {}

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="§unused-music§", intents=intents, help_command=None)

    async def setup_hook(self):
        # Configure the public Lavalink node
        uri = os.getenv("LAVALINK_URI", "https://lavalink.darrennathanael.com") # Note: Usually port 443 with HTTPS
        password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
        
        # Connect to NodePool
        node = wavelink.Node(uri=uri, password=password)
        try:
            await wavelink.Pool.connect(nodes=[node], client=self, cache_capacity=100)
            print("🔗 Connected to Lavalink Node")
        except Exception as e:
            print(f"❌ Failed to connect to Lavalink: {e}")

    async def on_ready(self):
        print("🔄 Syncing music bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("music", self)
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["music"]["status"]))

bot = MusicBot()
tree = bot.tree
install_error_handler(tree)

@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    print(f"🎵 Wavelink Node {payload.node.identifier} is ready!")

@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    player: wavelink.Player | None = payload.player
    if not player:
        return
    # In Wavelink v3, if autoplay is partially enabled, the queue progresses automatically.
    # We only need to manually loop if looping is enabled.
    if payload.reason == "finished":
        pass # Autoplay handles queue.

# ── COMMANDS ────────────────────────────────────────────────────────────────

async def _ensure_vc(interaction: discord.Interaction) -> wavelink.Player | None:
    if not interaction.user.voice:
        await interaction.response.send_message("❌ You must be in a voice channel.", ephemeral=True)
        return None

    if not interaction.guild.voice_client:
        try:
            player: wavelink.Player = await interaction.user.voice.channel.connect(cls=wavelink.Player)
            player.autoplay = wavelink.AutoPlayMode.partial
            return player
        except Exception as e:
            await interaction.response.send_message(f"❌ Could not connect to voice: `{e}`", ephemeral=True)
            return None
    else:
        player: wavelink.Player = interaction.guild.voice_client
        if player.channel != interaction.user.voice.channel:
            await player.move_to(interaction.user.voice.channel)
        return player

@tree.command(name="play", description="Play a song from YouTube or Spotify")
@app_commands.describe(query="The song name, YouTube URL, or Spotify URL")
async def play(interaction: discord.Interaction, query: str):
    if not await guild_check(interaction): return
    await interaction.response.defer()

    player = await _ensure_vc(interaction)
    if not player:
        return

    try:
        tracks: wavelink.Search = await wavelink.Playable.search(query)
        if not tracks:
            await interaction.followup.send("❌ No tracks found.")
            return

        # Playable.search can return a Playlist or a list of Playables
        if isinstance(tracks, wavelink.Playlist):
            added = len(tracks.tracks)
            player.queue.put(tracks)
            msg = f"Added **{added}** tracks from playlist **{tracks.name}**."
            track = tracks.tracks[0]
        else:
            track: wavelink.Playable = tracks[0]
            player.queue.put(track)
            msg = f"Added **{track.title}** to the queue."

        if not player.playing:
            await player.play(player.queue.get())

        embed = (EmbedBuilder(color=Palette.PRIMARY)
                 .title("🎵 Playing Music" if not player.playing else "🎵 Added to Queue")
                 .description(f"**[{track.title}]({track.uri})**")
                 .fields(("Author", track.author or "Unknown"),
                         ("Duration", f"{track.length // 60000}:{track.length % 60000 // 1000:02d}"))
                 .branded("Music").build())
        
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Failed to play: `{e}`")

@tree.command(name="stop", description="Stop playback and clear the queue")
async def stop_cmd(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    player: wavelink.Player = interaction.guild.voice_client
    if not player:
        return await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)
    
    player.queue.clear()
    await player.stop()
    await interaction.response.send_message("⏹️ Playback stopped and queue cleared.")

@tree.command(name="skip", description="Skip the current track")
async def skip_cmd(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    player: wavelink.Player = interaction.guild.voice_client
    if not player:
        return await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)
    
    await player.skip()
    await interaction.response.send_message("⏭️ Track skipped.")

@tree.command(name="pause", description="Pause playback")
async def pause_cmd(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    player: wavelink.Player = interaction.guild.voice_client
    if not player or not player.playing:
        return await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)
    
    await player.pause(True)
    await interaction.response.send_message("⏸️ Playback paused.")

@tree.command(name="resume", description="Resume playback")
async def resume_cmd(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    player: wavelink.Player = interaction.guild.voice_client
    if not player or not player.paused:
        return await interaction.response.send_message("❌ Nothing is paused.", ephemeral=True)
    
    await player.pause(False)
    await interaction.response.send_message("▶️ Playback resumed.")

@tree.command(name="queue", description="Show the current music queue")
async def queue_cmd(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    player: wavelink.Player = interaction.guild.voice_client
    if not player or (not player.playing and player.queue.is_empty):
        return await interaction.response.send_message("❌ The queue is empty.", ephemeral=True)
    
    lines = []
    if player.current:
        lines.append(f"**Currently Playing:**\n`[{player.current.length // 60000}:{player.current.length % 60000 // 1000:02d}]` [{player.current.title}]({player.current.uri})\n")
    
    if not player.queue.is_empty:
        lines.append("**Up Next:**")
        for i, track in enumerate(player.queue):
            if i >= 10:
                lines.append(f"*...and {player.queue.count - 10} more.*")
                break
            lines.append(f"`{i+1}.` `[{track.length // 60000}:{track.length % 60000 // 1000:02d}]` [{track.title}]({track.uri})")
    
    embed = (EmbedBuilder(color=Palette.PRIMARY)
        .title("📋 Music Queue")
        .description("\n".join(lines))
        .fields(("Total", f"`{player.queue.count}` song(s)"), ("Volume", f"{player.volume}%"))
        .branded("Music").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="volume", description="Set playback volume")
@app_commands.describe(percent="Volume from 0 to 150")
async def volume(interaction: discord.Interaction, percent: int):
    if not await guild_check(interaction): return
    if percent < 0 or percent > 150:
        return await interaction.response.send_message("❌ Volume must be between 0 and 150.", ephemeral=True)
    
    player: wavelink.Player = interaction.guild.voice_client
    if not player:
        return await interaction.response.send_message("❌ Not connected to voice.", ephemeral=True)
    
    await player.set_volume(percent)
    await interaction.response.send_message(f"🔊 Volume set to **{percent}%**.")

@tree.command(name="loop", description="Toggle loop mode for the current track or queue")
@app_commands.describe(mode="Mode to loop")
@app_commands.choices(mode=[
    app_commands.Choice(name="Off", value=0),
    app_commands.Choice(name="Track", value=1),
    app_commands.Choice(name="Queue", value=2)
])
async def loop_cmd(interaction: discord.Interaction, mode: int = 1):
    if not await guild_check(interaction): return
    player: wavelink.Player = interaction.guild.voice_client
    if not player:
        return await interaction.response.send_message("❌ Not connected to voice.", ephemeral=True)
    
    q_mode = wavelink.QueueMode.normal
    if mode == 1: q_mode = wavelink.QueueMode.loop
    elif mode == 2: q_mode = wavelink.QueueMode.loop_all
    
    player.queue.mode = q_mode
    await interaction.response.send_message(f"🔁 Loop mode set to **{['Off', 'Track', 'Queue'][mode]}**.")

# ── SPOTIFY TRACKING ─────────────────────────────────────────────────────────

def spotify_load_or_create_db():
    global spotify_db_data
    if os.path.exists(SPOTIFY_DB_FILE):
        with open(SPOTIFY_DB_FILE, "r", encoding="utf-8") as f:
            try: spotify_db_data = json.load(f)
            except json.JSONDecodeError: spotify_db_data = {}
    else: spotify_db_data = {}; spotify_save_db()

def spotify_save_db():
    with open(SPOTIFY_DB_FILE, "w", encoding="utf-8") as f: json.dump(spotify_db_data, f, indent=4, ensure_ascii=False)

spotify_listening_cache: dict = {}

@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member) -> None:
    spotify = next((act for act in after.activities if isinstance(act, discord.Spotify)), None)
    if spotify:
        cache_key = (spotify.track_id, spotify.start)
        if spotify_listening_cache.get(after.id) == cache_key: return
        spotify_listening_cache[after.id] = cache_key
        uid = str(after.id); now = datetime.now(timezone.utc).isoformat()
        spotify_db_data.setdefault(uid, {})
        if spotify.track_id not in spotify_db_data[uid]:
            spotify_db_data[uid][spotify.track_id] = {"title": spotify.title, "artist": spotify.artist, "album": spotify.album, "album_cover_url": spotify.album_cover_url, "track_url": f"https://open.spotify.com/track/{spotify.track_id}", "listen_count": 0, "first_heard": now}
        spotify_db_data[uid][spotify.track_id]["listen_count"] += 1
        spotify_db_data[uid][spotify.track_id]["last_heard"] = now
        spotify_save_db()
    else: spotify_listening_cache.pop(after.id, None)

@tree.command(name="spotify_stats", description="Full Spotify listening overview for a user.")
@app_commands.describe(user="Whose stats to show (defaults to you)")
async def spotify_stats(interaction: discord.Interaction, user: _Optional[discord.User] = None) -> None:
    user = user or interaction.user
    data = spotify_db_data.get(str(user.id), {})
    if not data: return await interaction.response.send_message(f"**{user.display_name}** hasn't been caught listening yet!")
    total = sum(t["listen_count"] for t in data.values())
    songs = len(data)
    artists = len({t["artist"] for t in data.values()})
    top_track = max(data.values(), key=lambda t: t["listen_count"])
    
    embed = EmbedBuilder(color=Palette.SUCCESS).title(f"🎧 {user.display_name}'s Spotify Stats")
    embed.description = f"**Total Listens:** `{total}`\n**Unique Songs:** `{songs}`\n**Unique Artists:** `{artists}`"
    embed.add_field("Top Track", f"[{top_track['title']}]({top_track['track_url']})\nby {top_track['artist']}\n({top_track['listen_count']} listens)")
    if top_track.get("album_cover_url"): embed.set_thumbnail(url=top_track["album_cover_url"])
    embed.branded("Spotify Tracker")
    await interaction.response.send_message(embed=embed.build())

@tree.command(name="spotify_top", description="Show a user's top Spotify tracks.")
@app_commands.describe(user="Whose top tracks to show", page="Page number")
async def spotify_top(interaction: discord.Interaction, user: _Optional[discord.User] = None, page: int = 1) -> None:
    user = user or interaction.user
    data = spotify_db_data.get(str(user.id), {})
    if not data: return await interaction.response.send_message(f"**{user.display_name}** hasn't been caught listening yet!")
    tracks = sorted(data.values(), key=lambda t: t["listen_count"], reverse=True)
    max_pages = (len(tracks) - 1) // SPOTIFY_PER_PAGE + 1
    page = max(1, min(page, max_pages))
    start = (page - 1) * SPOTIFY_PER_PAGE; end = start + SPOTIFY_PER_PAGE
    
    desc = []
    for i, t in enumerate(tracks[start:end], start=start+1):
        desc.append(f"`{i}.` **[{t['title']}]({t['track_url']})** by {t['artist']} `({t['listen_count']} plays)`")
    
    embed = EmbedBuilder(color=Palette.SUCCESS).title(f"🔝 {user.display_name}'s Top Spotify Tracks").description("\n".join(desc)).footer(f"Page {page} of {max_pages}").build()
    await interaction.response.send_message(embed=embed)

spotify_load_or_create_db()
