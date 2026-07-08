"""
theme.py — Centralized color palette, emoji constants, and embed builder.
Imported by every bot so all embeds look like they came from one product.
"""
from __future__ import annotations
import discord
from datetime import datetime, timezone

BRAND = "Barm Assistant"
BRAND_EMOJI = "🤖"

class Palette:
    PRIMARY   = 0x5865F2
    SURFACE   = 0x2B2D31
    SUCCESS   = 0x57F287
    DANGER    = 0xED4245
    WARNING   = 0xFEE75C
    INFO      = 0x00B0F4
    SAYORIES  = 0xFFD166
    BOCCHIES  = 0xFF8FB3
    TIER_LOW  = 0x8BC34A
    TIER_MID  = 0xFFC107
    TIER_HIGH = 0xFF5722
    TIER_MAX  = 0x00E5FF
    QUOTE     = 0x00D1B2
    WORDLE    = 0x6AAA64

class Emojis:
    SAYORIES  = "🪙"
    BOCCHIES  = "🌸"
    STAR      = "⭐"
    TROPHY    = "🏆"
    HEART     = "❤️"
    FIRE      = "🔥"
    CROWN     = "👑"
    GEM       = "💎"
    SCROLL    = "📜"
    DICE      = "🎲"
    MUSIC     = "🎵"
    COIN      = "🪙"
    CHECK     = "✅"
    CROSS     = "❌"
    ARROW_R   = "→"
    ARROW_L   = "←"

class EmbedBuilder:
    def __init__(self, *, color: int = Palette.PRIMARY):
        self._embed = discord.Embed(color=color, timestamp=datetime.now(timezone.utc))

    def title(self, text: str) -> "EmbedBuilder":
        self._embed.title = text
        return self

    def description(self, text: str) -> "EmbedBuilder":
        self._embed.description = text
        return self

    def field(self, name: str, value: str, *, inline: bool = True) -> "EmbedBuilder":
        self._embed.add_field(name=str(name)[:256], value=(str(value) or "\u200b")[:1024], inline=inline)
        return self

    def fields(self, *fields: tuple[str, str], inline: bool = True) -> "EmbedBuilder":
        for name, value in fields:
            self.field(name, value, inline=inline)
        return self

    def separator(self) -> "EmbedBuilder":
        self._embed.add_field(name="\u200b", value="\u200b", inline=False)
        return self

    def thumbnail(self, url: str) -> "EmbedBuilder":
        if url:
            self._embed.set_thumbnail(url=str(url))
        return self

    def image(self, url: str) -> "EmbedBuilder":
        if url:
            self._embed.set_image(url=str(url))
        return self

    def author(self, name: str, *, icon_url: str | None = None) -> "EmbedBuilder":
        kwargs = {"name": str(name)[:256]}
        if icon_url:
            kwargs["icon_url"] = str(icon_url)
        self._embed.set_author(**kwargs)
        return self

    def footer(self, text: str = "") -> "EmbedBuilder":
        self._embed.set_footer(text=text or f"{BRAND_EMOJI} {BRAND}")
        return self

    def branded(self, bot_label: str = "") -> "EmbedBuilder":
        suffix = f" • {bot_label}" if bot_label else ""
        self._embed.set_footer(text=f"{BRAND_EMOJI} {BRAND}{suffix}")
        return self

    def build(self) -> discord.Embed:
        if not getattr(self._embed.footer, "text", None):
            self._embed.set_footer(text=f"{BRAND_EMOJI} {BRAND}")
        return self._embed

    def __call__(self) -> discord.Embed:
        return self.build()

def success(title: str, description: str = "") -> discord.Embed:
    return EmbedBuilder(color=Palette.SUCCESS).title(f"{Emojis.CHECK} {title}").description(description).branded().build()

def error(title: str, description: str = "") -> discord.Embed:
    return EmbedBuilder(color=Palette.DANGER).title(f"{Emojis.CROSS} {title}").description(description).branded().build()

def info(title: str, description: str = "") -> discord.Embed:
    return EmbedBuilder(color=Palette.INFO).title(title).description(description).branded().build()

def progress_bar(current: int, maximum: int, length: int = 16, filled: str = "█", empty: str = "░") -> str:
    if maximum <= 0:
        return filled * length + " MAX"
    ratio = max(0.0, min(1.0, current / maximum))
    filled_count = round(ratio * length)
    return f"[{filled * filled_count}{empty * (length - filled_count)}]"
