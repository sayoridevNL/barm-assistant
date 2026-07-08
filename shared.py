"""
shared.py — Common config, persistence, economy, and UI helpers used by every
Barm assistant bot.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import discord
from discord.ext import commands

# ── .env LOADER ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

def _load_dotenv(path: str = ".env"):
    p = BASE_DIR / path
    if not p.exists(): return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)

_load_dotenv()

# ── CONFIG ───────────────────────────────────────────────────────────────────
BOT_OWNER_ID = int(os.getenv("SAYORIE_OWNER_ID", "1043235209639886972"))
BRAND = "Barm Assistant"

BOT_INFO = {
    "music":      {"color": 0x1ED760, "emoji": "🎵", "label": "Music",      "status": "🎵 /play music"},
    "moderation": {"color": 0xED4245, "emoji": "🔨", "label": "Moderation", "status": "🔨 keeping the peace"},
    "community":  {"color": 0xFF69B4, "emoji": "🌸", "label": "Community",  "status": "🌸 wees eens aardig tegen bram"},
    "gambling":   {"color": 0xFFD700, "emoji": "🎰", "label": "Gambling",   "status": "🎰 /slots /blackjack"},
    "umamusume":  {"color": 0xB983FF, "emoji": "🐴", "label": "Umamusume",  "status": "🐴 haru urara"},
    "general":    {"color": 0x5865F2, "emoji": "⚙️", "label": "General",    "status": "⚙️ /help for commands"},
}

# ── PERSISTENCE ──────────────────────────────────────────────────────────────
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
_locks: dict[int, asyncio.Lock] = {}

def _db_path(guild_id: int) -> Path: return DATA_DIR / f"{guild_id}.json"
def _db_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in _locks: _locks[guild_id] = asyncio.Lock()
    return _locks[guild_id]

def _db_load(guild_id: int) -> dict:
    p = _db_path(guild_id)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f: 
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}

def _db_save(guild_id: int, data: dict):
    with open(_db_path(guild_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def db_get_section(guild_id: int, section: str) -> dict:
    async with _db_lock(guild_id): return _db_load(guild_id).get(section, {})

async def db_save_section(guild_id: int, section: str, data: dict):
    async with _db_lock(guild_id):
        d = _db_load(guild_id)
        d[section] = data
        _db_save(guild_id, d)

async def db_get(guild_id: int, *keys, default=None):
    async with _db_lock(guild_id):
        d = _db_load(guild_id)
        for k in keys:
            if not isinstance(d, dict) or k not in d: return default
            d = d[k]
        return d

async def db_set(guild_id: int, value, *keys):
    async with _db_lock(guild_id):
        d = _db_load(guild_id)
        ref = d
        for k in keys[:-1]: ref = ref.setdefault(k, {})
        ref[keys[-1]] = value
        _db_save(guild_id, d)

# ── GLOBAL DATA ──────────────────────────────────────────────────────────────
GLOBAL_FILE = DATA_DIR / "global.json"
_global_lock = asyncio.Lock()

def _load_global() -> dict:
    if GLOBAL_FILE.exists():
        try:
            with open(GLOBAL_FILE, encoding="utf-8") as f: 
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"economy": {}, "levels": {}, "quotes": {}}

def _save_global(data: dict):
    with open(GLOBAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def global_get_section(section: str) -> dict:
    async with _global_lock: return _load_global().get(section, {})

async def global_save_section(section: str, data: dict):
    async with _global_lock:
        d = _load_global()
        d[section] = data
        _save_global(d)

# ── ECONOMY ──────────────────────────────────────────────────────────────────
async def g_eco_get(user_id: int) -> int:
    eco = await global_get_section("economy")
    return eco.get(str(user_id), {}).get("balance", 0)

async def g_eco_add(user_id: int, amount: int) -> int:
    async with _global_lock:
        d = _load_global()
        eco = d.setdefault("economy", {})
        uid = str(user_id)
        eco.setdefault(uid, {})
        eco[uid]["balance"] = max(0, eco[uid].get("balance", 0) + amount)
        _save_global(d)
        return eco[uid]["balance"]

async def g_eco_set(user_id: int, amount: int):
    async with _global_lock:
        d = _load_global()
        eco = d.setdefault("economy", {})
        uid = str(user_id)
        eco.setdefault(uid, {})
        eco[uid]["balance"] = max(0, amount)
        _save_global(d)

# ── TIER SYSTEM ──────────────────────────────────────────────────────────────
TIER_EMOJIS = {1: "🌱", 2: "🌿", 3: "🍃", 4: "🌸", 5: "🌺", 6: "⭐", 7: "🌟", 8: "💫", 9: "✨", 10: "🔥", 11: "🌊", 12: "⚡", 13: "🌪️", 14: "❄️", 15: "🌈", 16: "💎", 17: "🏆", 18: "👑", 19: "🦋", 20: "🐉", 21: "🌌", 22: "⚜️", 23: "🔮", 24: "🌠", 25: "💠"}
TIER_TITLES = {1: "Seedling", 2: "Sprout", 3: "Sapling", 4: "Blossom", 5: "Bloom", 6: "Rising Star", 7: "Shining Star", 8: "Radiant", 9: "Glimmering", 10: "Blazing", 11: "Tidal Force", 12: "Thunderstruck", 13: "Tempest", 14: "Frostbound", 15: "Prism Walker", 16: "Diamond", 17: "Champion", 18: "Crowned", 19: "Transcendent", 20: "Dragonheart", 21: "Cosmic", 22: "Exalted", 23: "Arcane Master", 24: "Celestial", 25: "Sayorie Legend"}
TIER_COLORS = {1: 0x8BC34A, 2: 0x66BB6A, 3: 0x26A69A, 4: 0xEC407A, 5: 0xE91E63, 6: 0xFDD835, 7: 0xFFEB3B, 8: 0xFFD600, 9: 0xFFC107, 10: 0xFF5722, 11: 0x29B6F6, 12: 0xFFEB3B, 13: 0x78909C, 14: 0x80DEEA, 15: 0x7E57C2, 16: 0x00BCD4, 17: 0xFFD700, 18: 0xFFD700, 19: 0xCE93D8, 20: 0xEF5350, 21: 0x1A237E, 22: 0xB8860B, 23: 0x9C27B0, 24: 0xE3F2FD, 25: 0x00E5FF}

def sayories_threshold_for_tier(tier: int) -> int:
    if tier <= 0: return 0
    base = 2400
    total = 0
    for t in range(1, tier + 1):
        multiplier = 1.80 ** (t - 1)
        extra_penalty = t * 100
        total += int(base * multiplier + extra_penalty)
    return total

xp_threshold_for_tier = sayories_threshold_for_tier

def tier_from_xp(sayories: int) -> int:
    for t in range(25, 0, -1):
        if sayories >= sayories_threshold_for_tier(t): return t
    return 0

def xp_for_next_tier(current_sayories: int) -> tuple[int, int, int]:
    ct = tier_from_xp(current_sayories)
    if ct >= 25: return 25, 0, 0
    threshold_current = sayories_threshold_for_tier(ct)
    threshold_next = sayories_threshold_for_tier(ct + 1)
    return ct, current_sayories - threshold_current, threshold_next - threshold_current

def build_xp_bar(into: int, needed: int, length: int = 16) -> str:
    if needed == 0: return "█" * length + " MAX"
    filled = int((into / needed) * length)
    filled = max(0, min(length, filled))
    return f"[{'█' * filled}{'░' * (length - filled)}]"

async def assign_tier_role(member: discord.Member, tier: int):
    if tier == 0: return
    to_remove = [r for r in member.roles if r.name.startswith("Level ")]
    if to_remove:
        try: await member.remove_roles(*to_remove, reason="Tier update")
        except Exception: pass
    role = discord.utils.get(member.guild.roles, name=f"Level {tier}")
    if role:
        try: await member.add_roles(role, reason=f"Reached Level {tier}")
        except Exception: pass

# ── BOCCHIES ─────────────────────────────────────────────────────────────────
BOCCHI_RANK_EMOJIS = {1: "🌸", 2: "🌷", 3: "💮", 4: "🎀", 5: "🎆", 6: "💜", 7: "🔮", 8: "👑", 9: "🌠", 10: "💗"}
BOCCHI_RANK_TITLES = {1: "Tier 1", 2: "Tier 2", 3: "Tier 3", 4: "Tier 4", 5: "Tier 5", 6: "Tier 6", 7: "Tier 7", 8: "Tier 8", 9: "Tier 9", 10: "Tier 10"}
BOCCHI_RANK_COLORS = {1: 0xFFB7C5, 2: 0xFF85A1, 3: 0xFF5C8D, 4: 0xFF2D75, 5: 0xE0005E, 6: 0xB8006C, 7: 0x8A007A, 8: 0x5C0088, 9: 0x2E0096, 10: 0xFF69B4}

def bocchies_threshold_for_rank(rank: int) -> int:
    if rank <= 0: return 0
    base = 3750
    total = 0
    for r in range(1, rank + 1):
        multiplier = 4.25 ** (r - 1)
        extra = (r ** 2) * 750
        total += int(base * multiplier + extra)
    return total

def bocchi_rank_from_points(points: int) -> int:
    for r in range(10, 0, -1):
        if points >= bocchies_threshold_for_rank(r): return r
    return 0

def bocchi_progress(points: int) -> tuple[int, int, int]:
    cr = bocchi_rank_from_points(points)
    if cr >= 10: return 10, 0, 0
    t_cur = bocchies_threshold_for_rank(cr)
    t_next = bocchies_threshold_for_rank(cr + 1)
    return cr, points - t_cur, t_next - t_cur

async def bocchi_get(guild_id: int, user_id: int) -> int:
    data = await db_get_section(guild_id, "bocchies")
    return data.get(str(user_id), {}).get("points", 0)

async def bocchi_add(guild_id: int, user_id: int, amount: int) -> int:
    async with _db_lock(guild_id):
        d = _db_load(guild_id)
        nat = d.setdefault("bocchies", {})
        uid = str(user_id)
        nat.setdefault(uid, {})
        nat[uid]["points"] = max(0, nat[uid].get("points", 0) + amount)
        _db_save(guild_id, d)
        return nat[uid]["points"]

async def bocchi_get_all(guild_id: int) -> dict:
    return await db_get_section(guild_id, "bocchies")

async def bocchi_get_role_cfg(guild_id: int) -> dict:
    return await db_get_section(guild_id, "bocchi_roles")

async def bocchi_set_role_cfg(guild_id: int, rank: int, role_id: int | None):
    async with _db_lock(guild_id):
        d = _db_load(guild_id)
        cfg = d.setdefault("bocchi_roles", {})
        if role_id is None: cfg.pop(str(rank), None)
        else: cfg[str(rank)] = role_id
        _db_save(guild_id, d)

async def bocchi_assign_rank_role(member: discord.Member, rank: int):
    if rank == 0 or not member.guild: return
    cfg = await bocchi_get_role_cfg(member.guild.id)
    if not cfg: return
    all_role_ids = set(cfg.values())
    to_remove = [r for r in member.roles if r.id in all_role_ids]
    if to_remove:
        try: await member.remove_roles(*to_remove, reason="Bocchi rank update")
        except Exception: pass
    new_role_id = cfg.get(str(rank))
    if new_role_id:
        new_role = member.guild.get_role(new_role_id)
        if new_role:
            try: await member.add_roles(new_role, reason=f"Bocchi Tier {rank} reached")
            except Exception: pass

# ── GENERIC CHECKS ───────────────────────────────────────────────────────────
def get_scope_id(interaction: discord.Interaction) -> int:
    return interaction.guild_id if interaction.guild_id else interaction.user.id

async def guild_check(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        await interaction.response.send_message("❌ This command only works inside a server.", ephemeral=True)
        return False
    return True

async def dm_check(interaction: discord.Interaction) -> bool:
    return True

# ── UI HELPERS ───────────────────────────────────────────────────────────────
def make_embed(bot_key: str, title: str | None = None, description: str | None = None, color: int | None = None, footer: str | None = None) -> discord.Embed:
    info = BOT_INFO.get(bot_key, {})
    embed = discord.Embed(title=title, description=description, color=color if color is not None else info.get("color", discord.Color.blurple()), timestamp=datetime.now(timezone.utc))
    label = info.get("label", bot_key.title())
    emoji = info.get("emoji", "")
    embed.set_footer(text=footer or f"🤖 {BRAND} • {emoji} {label}".strip())
    return embed

def build_help_embed(bot_key: str, intro: str, sections: dict[str, list[str]]) -> discord.Embed:
    info = BOT_INFO.get(bot_key, {})
    embed = make_embed(bot_key, title=f"{info.get('emoji', '')} {info.get('label', bot_key.title())} Commands", description=intro)
    for name, lines in sections.items():
        embed.add_field(name=name, value="\n".join(lines), inline=False)
    return embed

# ── STARTUP HELPERS ──────────────────────────────────────────────────────────
async def sync_guild_safely(bot: commands.Bot, guild: discord.Guild) -> bool:
    try:
        await bot.tree.sync(guild=guild)
        return True
    except discord.HTTPException as e:
        if "50240" not in str(e) and "Entry Point" not in str(e): return False
    try:
        existing_g = await bot.http.get_guild_commands(bot.application_id, guild.id)
        ep_cmds_g = [c for c in existing_g if c.get("type") == 4]
        payload_g = [c.to_dict(bot.tree) for c in bot.tree._get_all_commands(guild=guild)] + ep_cmds_g
        await bot.http.bulk_upsert_guild_commands(bot.application_id, guild.id, payload=payload_g)
        return True
    except Exception: return False

async def safe_sync(bot: commands.Bot):
    async def _safe_global_sync():
        try: return await bot.tree.sync()
        except discord.HTTPException as e:
            if "50240" not in str(e) and "Entry Point" not in str(e): raise
        existing = await bot.http.get_global_commands(bot.application_id)
        ep_cmds = [c for c in existing if c.get("type") == 4]
        payload = [c.to_dict(bot.tree) for c in bot.tree._get_all_commands(guild=None)] + ep_cmds
        return await bot.http.bulk_upsert_global_commands(bot.application_id, payload=payload)

    try:
        synced = await _safe_global_sync()
        print(f"  ✅ Global sync: {len(synced)} command(s)")
    except Exception as e:
        print(f"  ⚠️  Global sync failed: {e}")
    ok, fail = 0, 0
    for g in bot.guilds:
        if await sync_guild_safely(bot, g): ok += 1
        else: fail += 1
    print(f"  ✅ Guild sync: {ok} server(s) updated instantly" + (f" ({fail} failed)" if fail else ""))

def print_banner(bot_key: str, bot: commands.Bot):
    info = BOT_INFO.get(bot_key, {})
    guild_count = len(bot.guilds)
    member_total = sum(g.member_count or 0 for g in bot.guilds)
    print(f"\n{'─'*56}")
    print(f"  {info.get('emoji','')}  {info.get('label', bot_key.title())} bot online — {bot.user} (ID: {bot.user.id})")
    print(f"  🌐  Servers: {guild_count}   👥  Members: {member_total:,}")
    print(f"{'─'*56}\n")
