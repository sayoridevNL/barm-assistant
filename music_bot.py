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
    # Permissive format chain: try best audio, then audio (any codec), then best available.
    # This prevents "Requested format is not available" errors from killing extraction entirely.
    "format": "bestaudio[ext!=m4a]/bestaudio[ext!=webm]/bestaudio/best",
    "noplaylist": True, "quiet": True, "no_warnings": True,
    "default_search": "scsearch5", "source_address": "0.0.0.0", "age_limit": 99,
    "socket_timeout": 15,
}

# Build YouTube extractor args dynamically
_youtube_extractor_args: dict = {
    "player_client": ["android", "web", "ios"],
    "player_skip": ["webpage"],
    "skip": ["translated_subs"],
}

# PO token & visitor data from env (best way to bypass bot checks on cloud hosts)
_po_token = os.getenv("YOUTUBE_PO_TOKEN")
_visitor_data = os.getenv("YOUTUBE_VISITOR_DATA")
if _po_token:
    _youtube_extractor_args["po_token"] = [_po_token]
if _visitor_data:
    _youtube_extractor_args["visitor_data"] = _visitor_data

YDL_OPTIONS["extractor_args"] = {"youtube": _youtube_extractor_args}

# Cookie loading: file first, then base64 env var, then Render secret path
if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 200:
    YDL_OPTIONS["cookiefile"] = "cookies.txt"
elif os.path.exists("/etc/secrets/cookies.txt") and os.path.getsize("/etc/secrets/cookies.txt") > 200:
    YDL_OPTIONS["cookiefile"] = "/etc/secrets/cookies.txt"
elif os.getenv("YOUTUBE_COOKIES_B64"):
    import base64, tempfile
    _decoded = base64.b64decode(os.getenv("YOUTUBE_COOKIES_B64"))
    _tf = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False)
    _tf.write(_decoded)
    _tf.close()
    YDL_OPTIONS["cookiefile"] = _tf.name

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
    spotify_note = None
    
    if "open.spotify.com/track" in url:
        try:
            import urllib.request, json as _json
            oembed_api = f"https://open.spotify.com/oembed?url={url}"
            req = urllib.request.Request(oembed_api, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp: meta = _json.loads(resp.read())
            track_title = meta.get("title", "")
            if track_title: 
                actual_url = f"scsearch5:{track_title}"
                spotify_note = track_title
        except Exception: actual_url = f"scsearch5:{url}"
    elif not url.startswith("http"):
        actual_url = f"scsearch5:{url}"

    def _fetch():
        import urllib.request, json as _json
        
        # If it's a YouTube URL, try to bypass IP blocks using Piped and Invidious APIs first
        proxy_errors = []
        if "youtube.com" in actual_url or "youtu.be" in actual_url:
            vid = actual_url.split("v=")[-1].split("?")[0].split("&")[0]
            if "youtu.be/" in actual_url: vid = actual_url.split("youtu.be/")[-1].split("?")[0]
            
            # Try Piped instances (usually best reliability for audio extraction)
            piped_apis = [
                "https://pipedapi.kavin.rocks",
                "https://pipedapi.tokhmi.xyz",
                "https://pipedapi.adminforge.de",
                "https://api.piped.projectsegfault.com",
            ]
            for api in piped_apis:
                try:
                    req = urllib.request.Request(f"{api}/streams/{vid}", headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = _json.loads(resp.read().decode('utf-8'))
                        if "error" in data: raise ValueError(data["error"])
                        streams = data.get("audioStreams", [])
                        if streams:
                            streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
                            return (f"https://youtube.com/watch?v={vid}", streams[0]["url"], data.get("title", "Unknown"), int(data.get("duration", 0)), data.get("thumbnailUrl"))
                except Exception as e: proxy_errors.append(f"Piped {api}: {e}")

            # Try Invidious instances (fallback if Piped all fail)
            inv_apis = [
                "https://inv.nadeko.net",
                "https://invidious.tiekoetter.com",
                "https://iv.datura.network",
                "https://y.com.sb",
            ]
            for api in inv_apis:
                try:
                    req = urllib.request.Request(f"{api}/api/v1/videos/{vid}", headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = _json.loads(resp.read().decode('utf-8'))
                        formats = [f for f in data.get("adaptiveFormats", []) if f.get("type", "").startswith("audio/")]
                        if formats:
                            formats.sort(key=lambda x: int(x.get("bitrate", 0)), reverse=True)
                            thumb = data.get("videoThumbnails", [{}])[0].get("url") if data.get("videoThumbnails") else None
                            return (f"https://youtube.com/watch?v={vid}", formats[0]["url"], data.get("title", "Unknown"), int(data.get("lengthSeconds", 0)), thumb)
                except Exception as e: proxy_errors.append(f"Inv {api}: {e}")

        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            try:
                if actual_url.startswith("scsearch"):
                    flat_ydl = yt_dlp.YoutubeDL({**YDL_OPTIONS, "extract_flat": True})
                    info = flat_ydl.extract_info(actual_url, download=False)
                    urls_to_try = [e['url'] for e in info.get("entries", []) if e.get('url')]
                    if not urls_to_try: urls_to_try = [actual_url]
                else:
                    urls_to_try = [actual_url]
            except Exception:
                urls_to_try = [actual_url]

            last_err = None
            for u in urls_to_try:
                # Try preferred format first; on "format not available", retry with wide-open format
                for fmt_opts in [
                    YDL_OPTIONS,
                    {**YDL_OPTIONS, "format": "best"},  # last resort — take whatever YouTube gives
                ]:
                    try:
                        with yt_dlp.YoutubeDL(fmt_opts) as retry_ydl:
                            info = retry_ydl.extract_info(u, download=False)
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
                        if stream_url:
                            return (info.get("webpage_url") or stream_url, stream_url, info.get("title", "Unknown"), info.get("duration", 0), info.get("thumbnail", None))
                    except yt_dlp.utils.DownloadError as e:
                        err_str = str(e)
                        if "format" in err_str.lower():
                            last_err = e
                            continue  # retry with looser format
                        last_err = e
                        break
                    except Exception as e:
                        last_err = e
                        break
                proxy_errors.append(f"yt-dlp ({u}): {last_err}")

            raise ValueError(
                f"All sources failed or DRM protected.\n\n"
                f"**Proxy Errors:** {proxy_errors}\n\n"
                f"**Last yt-dlp error:** {last_err}\n\n"
                f"**How to fix this:**\n"
                f"YouTube is blocking your server's IP. You have 3 options:\n"
                f"1. Use `/set_youtube_cookies` and upload a valid cookies.txt from a logged-in browser.\n"
                f"2. Set a `YOUTUBE_PO_TOKEN` environment variable (best method).\n"
                f"3. Set `YOUTUBE_COOKIES_B64` env var with base64-encoded cookies.\n"
                f"See: https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide"
            )

    try:
        loop = asyncio.get_running_loop()
        page_url, stream_url, title, duration, thumbnail = await loop.run_in_executor(None, _fetch)
    except Exception as e:
        err_msg = str(e)
        return await interaction.followup.send("❌ Could not fetch audio:\n```\n" + err_msg[:1900] + "\n```")

    vc = await bot._ensure_vc(interaction)
    if vc is None: return

    track = {"url": stream_url, "page_url": page_url, "title": title, "requester": interaction.user, "duration": duration, "thumbnail": thumbnail}
    q = bot.music_q(interaction.guild_id)
    q.queue.append(track)

    mins, secs = divmod(int(duration), 60)
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

@tree.command(name="set_youtube_cookies", description="[ADMIN] Upload a cookies.txt file to fix YouTube bot blocks")
@app_commands.describe(cookie_file="The cookies.txt file you exported from your browser")
@app_commands.default_permissions(administrator=True)
async def set_youtube_cookies(interaction: discord.Interaction, cookie_file: discord.Attachment):
    if not cookie_file.filename.endswith(".txt"):
        return await interaction.response.send_message("❌ Please upload a .txt file", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        content = await cookie_file.read()
        with open("cookies.txt", "wb") as f:
            f.write(content)
        YDL_OPTIONS["cookiefile"] = "cookies.txt"
        await interaction.followup.send("✅ **YouTube Cookies successfully installed!**\nyt-dlp has been updated. Try playing a song now!")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to process cookies: `{e}`")

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
        dur = int(q.current.get("duration", 0)); mins, secs = divmod(dur, 60)
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
        mins, secs = divmod(int(duration), 60)
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
