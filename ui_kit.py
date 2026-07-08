"""
ui_kit.py — Reusable discord.ui Views, cooldown helpers, and the centralized
error handler. Drop these into any bot for instant consistency.
"""
from __future__ import annotations
import io
import os
import time
import unicodedata
from typing import Any, Sequence

import discord
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont

from theme import error as error_embed

class CooldownMap:
    def __init__(self, default_ttl: float = 60.0, clean_every: float = 300.0):
        self._store: dict[Any, float] = {}
        self._default_ttl = default_ttl
        self._clean_every = clean_every
        self._last_clean = time.monotonic()

    def check(self, key: Any, ttl: float | None = None) -> bool:
        now = time.monotonic()
        if now - self._last_clean > self._clean_every:
            self._clean(now)
            self._last_clean = now
        ttl = ttl if ttl is not None else self._default_ttl
        last = self._store.get(key, 0.0)
        if now - last >= ttl:
            self._store[key] = now
            return True
        return False

    def remaining(self, key: Any, ttl: float | None = None) -> float:
        ttl = ttl if ttl is not None else self._default_ttl
        last = self._store.get(key, 0.0)
        return max(0.0, ttl - (time.monotonic() - last))

    def reset(self, key: Any) -> None:
        self._store.pop(key, None)

    def _clean(self, now: float) -> None:
        cutoff = now - self._default_ttl * 2
        self._store = {k: v for k, v in self._store.items() if v > cutoff}

class Paginator(discord.ui.View):
    def __init__(self, pages: Sequence[discord.Embed], *, author_id: int, timeout: float = 120.0, start_page: int = 0):
        super().__init__(timeout=timeout)
        if not pages:
            raise ValueError("Paginator needs at least one page")
        self.pages = list(pages)
        self.author_id = author_id
        self.current = max(0, min(start_page, len(pages) - 1))
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_btn.disabled = self.current <= 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        self.counter.label = f"{self.current + 1} / {len(self.pages)}"

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who ran this command can flip pages.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def counter(self, interaction: discord.Interaction, _: discord.ui.Button):
        pass

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

class ConfirmView(discord.ui.View):
    def __init__(self, *, author_id: int, confirm_label: str = "Confirm", confirm_style: discord.ButtonStyle = discord.ButtonStyle.danger, cancel_label: str = "Cancel", timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.result: bool | None = None
        self.confirm_btn.label = confirm_label
        self.confirm_btn.style = confirm_style
        self.confirm_btn.emoji = "✅"
        self.cancel_btn.label = cancel_label
        self.cancel_btn.emoji = "✖️"

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This confirmation isn't yours to click.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.result = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.result = False
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        self.result = False
        for item in self.children:
            item.disabled = True

async def ask_confirm(interaction: discord.Interaction, embed: discord.Embed, **kwargs) -> bool:
    view = ConfirmView(author_id=interaction.user.id, **kwargs)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()
    return view.result is True

def install_error_handler(tree: app_commands.CommandTree) -> None:
    @tree.error
    async def on_app_command_error(interaction: discord.Interaction, err: app_commands.AppCommandError) -> None:
        if isinstance(err, app_commands.CommandInvokeError) and err.original:
            err = err.original
        if isinstance(err, app_commands.MissingPermissions):
            title, desc = "Missing Permissions", f"You need:\n```{', '.join(err.missing_permissions)}```"
        elif isinstance(err, app_commands.BotMissingPermissions):
            title, desc = "Bot Missing Permissions", f"I need:\n```{', '.join(err.missing_permissions)}```"
        elif isinstance(err, app_commands.CommandOnCooldown):
            title, desc = "Command on Cooldown", f"Try again in **{err.retry_after:.1f}s**."
        elif isinstance(err, app_commands.CheckFailure):
            title, desc = "Cannot Use This Command", str(err) or "You don't meet the requirements."
        else:
            raw = str(err) or err.__class__.__name__
            desc = f"```{raw[:900]}```\nIf this persists, contact an admin."
            title = "Something Went Wrong"
        
        embed = error_embed(title, desc)
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send(embed=embed, ephemeral=True)

# ── Image Helpers ───────────────────────────────────────────────────────────
_FONT_CACHE: dict[tuple[str, int], ImageFont.ImageFont] = {}
_FONT_PATHS_BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/liberation/LiberationSans-Bold.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf"]
_FONT_PATHS_REG = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/liberation/LiberationSans-Regular.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf"]
_FONT_PATHS_ITALIC = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/liberation/LiberationSans-Italic.ttf", "C:/Windows/Fonts/segoeuii.ttf", "C:/Windows/Fonts/ariali.ttf", "/Library/Fonts/Arial Italic.ttf"]
_FONT_PATHS_EMOJI = ["C:/Windows/Fonts/seguiemj.ttf", "C:/Windows/Fonts/seguisym.ttf", "/System/Library/Fonts/Apple Color Emoji.ttc", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf", "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf"]

def _find_font(paths: list[str]) -> str | None:
    for p in paths:
        if os.path.exists(p):
            return p
    return None

_FONT_BOLD = _find_font(_FONT_PATHS_BOLD)
_FONT_REG = _find_font(_FONT_PATHS_REG)
_FONT_ITALIC = _find_font(_FONT_PATHS_ITALIC)
_FONT_EMOJI = _find_font(_FONT_PATHS_EMOJI)

def load_font(style: str = "regular", size: int = 20) -> ImageFont.ImageFont:
    key = (style, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = {"bold": _FONT_BOLD, "regular": _FONT_REG, "italic": _FONT_ITALIC, "emoji": _FONT_EMOJI}.get(style)
    if path:
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = font
            return font
        except Exception:
            pass
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font

def _is_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or cp in {0x200D, 0x20E3, 0xFE0F}
        or unicodedata.category(ch) == "So"
    )

def _split_clusters(text: str) -> list[str]:
    clusters: list[str] = []
    i = 0
    while i < len(text):
        cluster = text[i]
        i += 1
        while i < len(text):
            ch = text[i]
            cp = ord(ch)
            if cp in {0xFE0E, 0xFE0F, 0x20E3} or unicodedata.combining(ch):
                cluster += ch
                i += 1
                continue
            if ch == "\u200d":
                cluster += ch
                i += 1
                if i < len(text):
                    cluster += text[i]
                    i += 1
                continue
            if 0x1F3FB <= cp <= 0x1F3FF:
                cluster += ch
                i += 1
                continue
            break
        clusters.append(cluster)
    return clusters

def _cluster_font(cluster: str, primary: ImageFont.ImageFont, emoji: ImageFont.ImageFont | None) -> ImageFont.ImageFont:
    if emoji and any(_is_emoji_char(ch) for ch in cluster):
        return emoji
    return primary

def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[float, float]:
    if not text:
        return 0.0, 0.0
    width = draw.textlength(text, font=font)
    bbox = draw.textbbox((0, 0), text, font=font)
    return width, float(bbox[3] - bbox[1])

def text_size_with_fallback(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, emoji_font: ImageFont.ImageFont | None = None) -> tuple[float, float]:
    from pilmoji import Pilmoji
    if not hasattr(draw, '_image'): return 0.0, 0.0
    with Pilmoji(draw._image) as pilmoji:
        w, h = pilmoji.getsize(text, font=font)
        return float(w), float(h)

def draw_text_with_fallback(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font: ImageFont.ImageFont, fill, *, emoji_font: ImageFont.ImageFont | None = None, anchor: str | None = None) -> None:
    from pilmoji import Pilmoji
    if not hasattr(draw, '_image'): return
    
    x, y = xy
    if anchor:
        width, height = text_size_with_fallback(draw, text, font, emoji_font)
        if anchor[0] == "m":
            x -= width / 2
        elif anchor[0] == "r":
            x -= width
        if len(anchor) > 1:
            if anchor[1] == "m":
                y -= height / 2
            elif anchor[1] in {"b", "d"}:
                y -= height

    with Pilmoji(draw._image) as pilmoji:
        pilmoji.text((x, y), text, fill=fill, font=font)

def wrap_text_pixels(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, *, max_lines: int | None = None, emoji_font: ImageFont.ImageFont | None = None) -> list[str]:
    emoji_font = emoji_font or load_font("emoji", getattr(font, "size", 20))
    words = text.replace("\n", " \n ").split(" ")
    lines: list[str] = []
    current = ""

    def fits(candidate: str) -> bool:
        return text_size_with_fallback(draw, candidate, font, emoji_font)[0] <= max_width

    for word in words:
        if word == "\n":
            lines.append(current.rstrip())
            current = ""
            continue
        candidate = word if not current else f"{current} {word}"
        if fits(candidate):
            current = candidate
            continue
        if current:
            lines.append(current.rstrip())
            current = word
        else:
            chopped = ""
            for cluster in _split_clusters(word):
                if chopped and not fits(chopped + cluster):
                    lines.append(chopped)
                    chopped = cluster
                else:
                    chopped += cluster
            current = chopped
        if max_lines and len(lines) >= max_lines:
            break

    if current and (max_lines is None or len(lines) < max_lines):
        lines.append(current.rstrip())

    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
    if max_lines and lines and len(lines) == max_lines and " ".join(words).strip() != " ".join(lines).strip():
        ellipsis = "..."
        while lines[-1] and not fits(lines[-1] + ellipsis):
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip() + ellipsis
    return lines or [""]

def truncate_text_pixels(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, *, emoji_font: ImageFont.ImageFont | None = None) -> str:
    emoji_font = emoji_font or load_font("emoji", getattr(font, "size", 20))
    if text_size_with_fallback(draw, text, font, emoji_font)[0] <= max_width:
        return text
    out = ""
    for cluster in _split_clusters(text):
        candidate = out + cluster
        if text_size_with_fallback(draw, candidate + "...", font, emoji_font)[0] > max_width:
            break
        out = candidate
    return out.rstrip() + "..."

def draw_gradient(draw: ImageDraw.ImageDraw, size: tuple[int, int], start: tuple[int, int, int], end: tuple[int, int, int], *, direction: str = "horizontal") -> None:
    w, h = size
    if direction == "horizontal":
        for x in range(w):
            t = x / max(w - 1, 1)
            r = int(start[0] + (end[0] - start[0]) * t)
            g = int(start[1] + (end[1] - start[1]) * t)
            b = int(start[2] + (end[2] - start[2]) * t)
            draw.line([(x, 0), (x, h)], fill=(r, g, b))
    else:
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(start[0] + (end[0] - start[0]) * t)
            g = int(start[1] + (end[1] - start[1]) * t)
            b = int(start[2] + (end[2] - start[2]) * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

def draw_starfield(draw: ImageDraw.ImageDraw, size: tuple[int, int], count: int = 80, seed: int = 42, brightness_range: tuple[int, int] = (40, 130)) -> None:
    import random
    rng = random.Random(seed)
    w, h = size
    lo, hi = brightness_range
    for _ in range(count):
        x, y = rng.randint(0, w), rng.randint(0, h)
        b = rng.randint(lo, hi)
        s = rng.choice([1, 1, 1, 2])
        draw.ellipse([(x - s, y - s), (x + s, y + s)], fill=(b, b, b, 180))

def circular_avatar(avatar_bytes: bytes, size: int = 160) -> Image.Image:
    img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (size, size)], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, mask=mask)
    return out

def to_discord_file(img: Image.Image, filename: str = "card.png") -> discord.File:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return discord.File(buf, filename=filename)

def resolve_mentions(text: str, guild: discord.Guild | None = None) -> str:
    import re
    def replacer(m: re.Match) -> str:
        uid = int(m.group(1))
        if guild:
            member = guild.get_member(uid)
            if member:
                return f"@{member.display_name}"
        return "@user"
    return re.sub(r"<@!?(\d+)>", replacer, text)
