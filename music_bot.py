from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional as _Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from shared import *
from theme import EmbedBuilder, Palette
from ui_kit import ask_confirm, install_error_handler

class MusicQueue:
    def __init__(self):
        self.queue: list[dict] = []
        self.current: dict | None = None
        self.volume: float = 0.5
        self.loop: bool = False

YDL_OPTIONS = {
    "format": "bestaudio/best", "noplaylist": True, "quiet": True, "no_warnings": True,
    "default_search": "scsearch", "source_address": "0.0.0.0", "age_limit": 99,
    "extractor_args": {"youtube": {"player_client": ["android", "ios"], "skip": ["translated_subs"]}},
    "socket_timeout": 15,
}
if os.path.exists("cookies.txt"):
    YDL_OPTIONS["cookiefile"] = "cookies.txt"
elif os.path.exists("/etc/secrets/cookies.txt"):
    YDL_OPTIONS["cookiefile"] = "/etc/secrets/cookies.txt"
FFMPEG_OPTIONS = {"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5", "options": "-vn"}

SPOTIFY_DB_FILE = "spotify_stats.json"
SPOTIFY_PER_PAGE = 15
spotify_db_data: dict = {}

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="§unused-music§", intents=intents, help_command=None)
        self._music: dict[int, MusicQueue] = {}

    def music_q(self, guild_id: int) -> MusicQueue:
        if guild_id not in self._music: self._music[guild_id] = MusicQueue()
        return self._music[guild_id]

    def _play_next(self, interaction: discord.Interaction, vc: discord.VoiceClient):
        q = self.music_q(interaction.guild_id)
        if not q.queue: q.current = None; return
        live_vc = interaction.guild.voice_client if interaction.guild else vc
        if live_vc is None or not live_vc.is_connected(): q.current = None; return
        track = q.queue.pop(0); q.current = track
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(track["url"], **FFMPEG_OPTIONS), volume=q.volume)
        loop = self.loop
        live_vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._after_play(interaction), loop))

    async def _after_play(self, interaction):
        await asyncio.sleep(1)
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc and vc.is_connected():
            q = self.music_q(interaction.guild_id)
            if q.loop and q.current: q.queue.insert(0, q.current)
            if q.queue:
                track = q.queue[0]
                if track.get("page_url"):
                    try:
                        loop = asyncio.get_running_loop()
                        def _refetch():
                            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                                info = ydl.extract_info(track["page_url"], download=False)
                                new_url = info.get("url")
                                if not new_url:
                                    formats = info.get("formats", [])
                                    audio_only = [f for f in formats if not f.get("height") and f.get("url")]
                                    if audio_only:
                                        audio_only.sort(key=lambda f: f.get("abr") or 0, reverse=True)
                                        new_url = audio_only[0]["url"]
                                    else:
                                        for f in reversed(formats):
                                            if f.get("url"): new_url = f["url"]; break
                                if new_url: track["url"] = new_url
                        await loop.run_in_executor(None, _refetch)
                    except Exception: pass
            self._play_next(interaction, vc)

    async def _ensure_vc(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        if interaction.user.voice is None:
            await interaction.followup.send("❌ You must be in a voice channel."); return None
        vc = interaction.guild.voice_client
        if vc is None:
            try:
                vc = await interaction.user.voice.channel.connect(self_deaf=True, reconnect=True, timeout=60.0)
                await asyncio.sleep(0.5)
            except asyncio.TimeoutError: await interaction.followup.send("❌ Timed out connecting to voice."); return None
            except discord.ClientException as e: await interaction.followup.send(f"❌ Voice connection error: `{e}`"); return None
        elif vc.channel != interaction.user.voice.channel: await vc.move_to(interaction.user.voice.channel)
        if not vc.is_connected(): await interaction.followup.send("❌ Voice connection dropped unexpectedly."); return None
        return vc

    async def on_ready(self):
        print("🔄 Syncing music bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("music", self)
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["music"]["status"]))

bot = MusicBot()
tree = bot.tree
install_error_handler(tree)

@tree.command(name="play", description="Play a song from a YouTube or Spotify URL, or search term")
@app_commands.describe(url="YouTube/Spotify URL or search query")
async def play(interaction: discord.Interaction, url: str):
    if not await guild_check(interaction): return
    if interaction.user.voice is None: return await interaction.response.send_message("❌ You must be in a voice channel.", ephemeral=True)
    await interaction.response.defer()

    actual_url = url
    
    # Bypass YouTube Bot Blocks by converting YouTube/Spotify URLs to SoundCloud searches
    if "youtube.com" in url or "youtu.be" in url:
        try:
            import urllib.request, json as _json
            noembed_api = f"https://noembed.com/embed?url={url}"
            req = urllib.request.Request(noembed_api, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                meta = _json.loads(resp.read().decode('utf-8'))
                track_title = meta.get("title", "")
                if track_title: actual_url = f"scsearch1:{track_title}"
        except Exception: pass
    elif "open.spotify.com/track" in url:
        try:
            import urllib.request, json as _json
            oembed_api = f"https://open.spotify.com/oembed?url={url}"
            req = urllib.request.Request(oembed_api, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp: meta = _json.loads(resp.read())
            track_title = meta.get("title", "")
            if track_title: actual_url = f"scsearch1:{track_title}"
        except Exception: actual_url = f"scsearch1:{url}"
    elif not url.startswith("http"):
        actual_url = f"scsearch1:{url}"

    def _fetch():
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(actual_url, download=False)
            if "entries" in info: info = info["entries"][0]
            stream_url = info.get("url")
            if not stream_url:
                formats = info.get("formats", [])
                audio_only = [f for f in formats if not f.get("height") and f.get("url")]
                if audio_only:
                    audio_only.sort(key=lambda f: f.get("abr") or 0, reverse=True)
                    stream_url = audio_only[0]["url"]
                else:
                    for f in reversed(formats):
                        if f.get("url"): stream_url = f["url"]; break
            if not stream_url: raise ValueError("yt-dlp returned no playable URL for this track.")
            return (info.get("webpage_url") or stream_url, stream_url, info.get("title", "Unknown"), info.get("duration", 0), info.get("thumbnail", None))

    try:
        loop = asyncio.get_running_loop()
        page_url, stream_url, title, duration, thumbnail = await loop.run_in_executor(None, _fetch)
    except Exception as e:
        return await interaction.followup.send(f"❌ Could not fetch audio: `{e}`")

    vc = await bot._ensure_vc(interaction)
    if vc is None: return

    track = {"url": stream_url, "page_url": page_url, "title": title, "requester": interaction.user, "duration": duration, "thumbnail": thumbnail}
    q = bot.music_q(interaction.guild_id)
    q.queue.append(track)

    mins, secs = divmod(duration, 60)
    embed = (EmbedBuilder(color=Palette.PRIMARY).title("🎵 Added to Queue").description(f"**{title}**").thumbnail(thumbnail).fields(("⏱️ Duration", f"{mins}:{secs:02d}"), ("📋 Queue Size", str(len(q.queue))), ("👤 Requested by", interaction.user.mention)).footer("Barm assistant Music").build())
    if spotify_note: embed.add_field(name="🎵 Via Spotify", value=f"Searched YouTube for: *{spotify_note}*", inline=False)
    await interaction.followup.send(embed=embed)

    if not vc.is_playing() and not vc.is_paused(): bot._play_next(interaction, vc)

@tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        embed = EmbedBuilder(color=Palette.WARNING).title("⏭️ Song Skipped").footer("Barm assistant Music").build()
        await interaction.response.send_message(embed=embed)
    else: await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)

@tree.command(name="stop", description="Stop playback, clear the queue, and leave voice")
async def stop(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    vc = interaction.guild.voice_client
    q = bot.music_q(interaction.guild_id)
    q.queue.clear()
    q.current = None
    if vc and (vc.is_connected() or vc.is_playing() or vc.is_paused()):
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        await vc.disconnect(force=False)
        embed = (EmbedBuilder(color=Palette.WARNING)
            .title("⏹️ Playback Stopped")
            .description("Queue cleared and voice connection closed.")
            .branded("Music").build())
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("❌ I'm not connected to a voice channel.", ephemeral=True)

@tree.command(name="nowplaying", description="Show the currently playing song")
async def nowplaying(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    q = bot.music_q(interaction.guild_id)
    if q.current:
        dur = q.current.get("duration", 0); mins, secs = divmod(dur, 60)
        embed = (EmbedBuilder(color=Palette.PRIMARY).title("🎵 Now Playing").description(f"**{q.current['title']}**").thumbnail(q.current.get("thumbnail")).fields(("⏱️ Duration", f"{mins}:{secs:02d}"), ("👤 Requested by", str(q.current["requester"])), ("📋 Up Next", str(len(q.queue)) + " song(s)"), ("🔁 Loop", "On" if q.loop else "Off")).footer("Barm assistant Music").build())
        await interaction.response.send_message(embed=embed)
    else: await interaction.response.send_message("❌ Nothing is playing.")

@tree.command(name="queue", description="Show the current music queue")
async def queue_cmd(interaction: discord.Interaction):
    if not await guild_check(interaction): return
    q = bot.music_q(interaction.guild_id)
    if not q.current and not q.queue:
        await interaction.response.send_message("❌ The queue is empty.", ephemeral=True)
        return

    lines = []
    if q.current:
        lines.append(f"**Now:** {q.current['title']}")
    for idx, track in enumerate(q.queue[:10], 1):
        duration = track.get("duration", 0)
        mins, secs = divmod(duration, 60)
        lines.append(f"`{idx}.` {track['title']} `[{mins}:{secs:02d}]`")
    if len(q.queue) > 10:
        lines.append(f"*...and {len(q.queue) - 10} more.*")

    embed = (EmbedBuilder(color=Palette.PRIMARY)
        .title("📋 Music Queue")
        .description("\n".join(lines))
        .fields(("Up Next", f"`{len(q.queue)}` song(s)"), ("Loop", "On" if q.loop else "Off"), ("Volume", f"{int(q.volume * 100)}%"))
        .branded("Music").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="loop", description="Toggle looping the current track")
@app_commands.describe(enabled="Leave blank to toggle")
async def loop_cmd(interaction: discord.Interaction, enabled: bool | None = None):
    if not await guild_check(interaction): return
    q = bot.music_q(interaction.guild_id)
    q.loop = (not q.loop) if enabled is None else enabled
    embed = (EmbedBuilder(color=Palette.SUCCESS if q.loop else Palette.WARNING)
        .title("🔁 Loop Updated")
        .description(f"Loop is now **{'on' if q.loop else 'off'}**.")
        .branded("Music").build())
    await interaction.response.send_message(embed=embed)

@tree.command(name="volume", description="Set playback volume")
@app_commands.describe(percent="Volume from 0 to 150")
async def volume(interaction: discord.Interaction, percent: int):
    if not await guild_check(interaction): return
    if percent < 0 or percent > 150:
        await interaction.response.send_message("❌ Volume must be between 0 and 150.", ephemeral=True)
        return
    q = bot.music_q(interaction.guild_id)
    q.volume = percent / 100
    vc = interaction.guild.voice_client
    if vc and isinstance(vc.source, discord.PCMVolumeTransformer):
        vc.source.volume = q.volume
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title("🔊 Volume Updated")
        .description(f"Playback volume set to **{percent}%**.")
        .branded("Music").build())
    await interaction.response.send_message(embed=embed)

# ── SPOTIFY TRACKING ─────────────────────────────────────────────────────────
spotify_listening_cache: dict = {}

def spotify_load_or_create_db():
    global spotify_db_data
    if os.path.exists(SPOTIFY_DB_FILE):
        with open(SPOTIFY_DB_FILE, "r", encoding="utf-8") as f:
            try: spotify_db_data = json.load(f)
            except json.JSONDecodeError: spotify_db_data = {}
    else: spotify_db_data = {}; spotify_save_db()

def spotify_save_db():
    with open(SPOTIFY_DB_FILE, "w", encoding="utf-8") as f: json.dump(spotify_db_data, f, indent=4, ensure_ascii=False)

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
    
    embed = (EmbedBuilder(color=Palette.SUCCESS).title(f"📊  Spotify Stats — {user.display_name}").thumbnail(user.display_avatar.url).fields(("🎵 Total Streams", f"`{total:,}`"), ("🎶 Unique Songs", f"`{songs:,}`"), ("🎤 Unique Artists", f"`{artists:,}`")).build())
    url = top_track.get("track_url", "#")
    embed.add_field(name="👑 All-Time Favourite", value=f"**[{top_track['title']}]({url})**\nby {top_track['artist']}  ·  `{top_track['listen_count']:,} streams`", inline=False)
    await interaction.response.send_message(embed=embed)

@tree.command(name="spotify_reset_stats", description="Permanently delete all YOUR Spotify listening stats.")
async def spotify_reset_stats(interaction: discord.Interaction) -> None:
    uid = str(interaction.user.id)
    if not spotify_db_data.get(uid): return await interaction.response.send_message("You don't have any Spotify stats to delete!", ephemeral=True)
    
    confirmed = await ask_confirm(interaction, EmbedBuilder(color=Palette.DANGER).title("⚠️  Confirm Spotify Stats Reset").description("This will **permanently erase** all your Spotify listening data.\n*This action cannot be undone.*").build(), confirm_label="Yes, delete everything")
    if confirmed:
        spotify_db_data.pop(uid, None)
        spotify_save_db()
        await interaction.followup.send("✅  Your Spotify listening history has been permanently erased. Fresh start! 🎵")

@tree.command(name="help", description="Show all Music bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("music", "Music playback and Spotify listening stats.", {"🎵 Playback": ["`/play <song>` — play from YouTube/Spotify URL or search", "`/skip` — skip the current song", "`/stop` — stop, clear queue, disconnect", "`/queue` — show upcoming songs", "`/nowplaying` — show the current song", "`/loop [enabled]` — toggle current-track looping", "`/volume <0-150>` — set playback volume"], "🎧 Spotify tracking": ["`/spotify_stats [user]` — full listening overview", "`/spotify_reset_stats` — wipe your own Spotify history"]})
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("MUSIC_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the MUSIC_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
