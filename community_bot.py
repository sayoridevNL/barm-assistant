"""
community_bot.py — Server engagement systems (Sayories Tier leveling, Bocchies,
quotes, word tracker, counting channels, gameplay-VC pinger) and lightweight
fun commands.
"""
from __future__ import annotations
import os
import random
import asyncio
import io
import json
import time
import uuid
from typing import Optional
import aiohttp

import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

from shared import *
from theme import EmbedBuilder, Palette, Emojis, progress_bar
from ui_kit import (
    CooldownMap,
    install_error_handler, load_font, draw_gradient, draw_starfield,
    circular_avatar, to_discord_file, resolve_mentions,
    draw_text_with_fallback, truncate_text_pixels, wrap_text_pixels,
)

class CommunityBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="§unused-community§", intents=intents, help_command=None)
        self.xp_cd = CooldownMap(default_ttl=60.0)
        self.chat_cd = CooldownMap(default_ttl=60.0)
        self.bocchi_cd = CooldownMap(default_ttl=120.0)
        self._msg_count: dict[int | str, int | bool] = {}
        self.cards_db = []
        self.load_cards()

    def load_cards(self):
        try:
            with open("support_cards.json", "r", encoding="utf-8") as f:
                self.cards_db = json.load(f)
        except Exception as e:
            print(f"Failed to load cards: {e}")


    async def setup_hook(self):
        self.add_view(SuggestionView())
        check_web_suggestions.start()
        try:
            await self.load_extension("sports_tracker")
        except Exception as exc:
            print(f"Failed to load sports_tracker: {exc}")
            import traceback
            traceback.print_exc()
        try:
            await self.add_cog(MarriageSystem(self))
            for name, _meta in ACTIONS.items():
                pretty = {"kiss": "Kiss", "hug": "Hug", "kill": "Playfully 'defeat' (duel)",
                          "nom": "Nom", "lick": "Lick", "tickle": "Tickle",
                          "touches": "Friendly touch/high-five", "griddy": "Griddy duel + dance"}[name]
                self.tree.add_command(self.get_cog("MarriageSystem")._register_action(
                    name, f"{pretty} another user (playful, non-graphic)"
                ))
        except Exception as exc:
            print(f"Failed to set up marriage system: {exc}")
            import traceback
            traceback.print_exc()

    @tasks.loop(seconds=60)
    async def vc_payout_loop(self) -> None:
        vc_sayories = 3
        for guild in self.guilds:
            for vc in guild.voice_channels:
                for member in [m for m in vc.members if not m.bot]:
                    await self._pay_vc_member(guild, member, vc_sayories)

    async def _pay_vc_member(self, guild: discord.Guild, member: discord.Member, amount: int) -> None:
        old_bal = await g_eco_get(member.id)
        old_tier = tier_from_xp(old_bal)
        new_bal = await g_eco_add(member.id, amount)
        new_tier = tier_from_xp(new_bal)

        if new_tier > old_tier and new_tier >= 1:
            await assign_tier_role(member, new_tier)

        nat_old = await bocchi_get(guild.id, member.id)
        nat_old_rank = bocchi_rank_from_points(nat_old)
        nat_new = await bocchi_add(guild.id, member.id, 1 if random.random() < 0.5 else 0)
        nat_new_rank = bocchi_rank_from_points(nat_new)
        if nat_new_rank > nat_old_rank and nat_new_rank >= 1:
            await bocchi_assign_rank_role(member, nat_new_rank)

    @tasks.loop(hours=168)
    async def weekly_reset(self) -> None:
        quotes = await global_get_section("quotes")
        if not quotes: return
        top_uid = max(quotes, key=lambda u: quotes[u].get("stars", 0))
        top_stars = quotes[top_uid].get("stars", 0)
        if top_stars == 0: return
        await g_eco_add(int(top_uid), 1000)
        await self._announce_weekly_winner(int(top_uid), top_stars)
        for uid in quotes: quotes[uid]["stars"] = 0
        await global_save_section("quotes", quotes)

    async def _announce_weekly_winner(self, winner_id: int, stars: int) -> None:
        for guild in self.guilds:
            member = guild.get_member(winner_id)
            if not member: continue
            embed = (EmbedBuilder(color=Palette.SAYORIES)
                .title(f"{Emojis.TROPHY} Weekly Quote Champion!")
                .description(f"### 🎊 {member.display_name} wins this week's global Quote Battle!\n\nThey earned **{stars} {Emojis.STAR}** and receive **1,000 Sayories** as a prize!\n\n*Stars reset for a new week. Good luck everyone!*")
                .thumbnail(member.display_avatar.url).branded("Quotes").build())
            for ch in guild.text_channels:
                try:
                    await ch.send(embed=embed)
                    return
                except discord.Forbidden: continue
                except Exception: continue
            return

    async def on_ready(self) -> None:
        print("🔄 Syncing community bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("community", self)
        self.vc_payout_loop.start()
        self.weekly_reset.start()
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["community"]["status"]))

# ══════════════════════════════════════════════════════════════════════════
# MARRIAGE SYSTEM — playful interaction commands + fictional consensual
# marriage/divorce system (halal = 2 people, harem = 3 or 4). Persists via
# shared.py's db_get_section/db_save_section, same pattern as the rest of
# this file (e.g. the cards gacha system below).
# ══════════════════════════════════════════════════════════════════════════
# ── Config (server owners can tune these; see CONFIG section at bottom) ──────
ACTION_COOLDOWN_SECONDS = 8.0
PROPOSAL_EXPIRY_SECONDS = 15 * 60
DIVORCE_EXPIRY_SECONDS = 24 * 60 * 60
JUDGE_ROLE_NAMES = {"judge", "marriage judge", "mod", "moderator"}  # fallback if no configured role

MODE_REQUIRED_COUNT = {
    "two_person": 2,
    "three_person": 3,
    "four_person": 4,
}
MODE_LABEL = {
    "two_person": "Halal Marriage 💍",
    "three_person": "Harem Marriage (Trio) 💞",
    "four_person": "Squad Marriage (Harem, 4) 💞",
}


# Uses shared.py's db_get_section/db_save_section, which persist to Mongo
# when MONGODB_URI is set, or to data/<guild_id>.json otherwise — same store
# every other bot module in this project already uses. Sections used here:
#   "marriages"         -> {marriage_id: {...}}
#   "marriage_divorces" -> {case_id: {...}}
#   "marriage_config"   -> {...}
# db_get_section/db_save_section each lock internally per-guild, but a
# read-modify-write across the two calls isn't atomic on its own, so we add
# an in-process lock around each read-modify-write sequence below.

_guild_locks: dict[int, asyncio.Lock] = {}


def _lock_for(guild_id: int) -> asyncio.Lock:
    if guild_id not in _guild_locks:
        _guild_locks[guild_id] = asyncio.Lock()
    return _guild_locks[guild_id]


def _default_config() -> dict:
    return {
        "enabled": True,
        "allow_bots": False,
        "allowed_modes": ["two_person", "three_person", "four_person"],
        "proposal_expiry": PROPOSAL_EXPIRY_SECONDS,
        "divorce_expiry": DIVORCE_EXPIRY_SECONDS,
        "judge_role_id": None,
        "log_channel_id": None,
        "shared_economy_enabled": False,
    }


async def get_config(guild_id: int) -> dict:
    stored = await db_get_section(guild_id, "marriage_config")
    cfg = _default_config()
    cfg.update(stored or {})
    return cfg


async def set_config(guild_id: int, **updates) -> dict:
    async with _lock_for(guild_id):
        cfg = _default_config()
        cfg.update(await db_get_section(guild_id, "marriage_config") or {})
        cfg.update(updates)
        await db_save_section(guild_id, "marriage_config", cfg)
        return cfg


def _active_marriage_for(marriages: dict, guild_id: int, user_id: int):
    for mid, m in marriages.items():
        if m["guild_id"] == guild_id and m["status"] == "active" and user_id in m["participants"]:
            return mid, m
    return None, None


def _active_proposal_involving(marriages: dict, guild_id: int, user_ids: set[int]):
    for mid, m in marriages.items():
        if m["guild_id"] == guild_id and m["status"] == "pending" and user_ids & set(m["participants"]):
            return mid, m
    return None, None


class MarriageDB:
    """Thin async-safe wrapper around the per-guild JSON store."""

    @staticmethod
    async def create_proposal(guild_id: int, mode: str, creator_id: int, participants: list[int]) -> dict:
        async with _lock_for(guild_id):
            marriages = await global_get_section("marriages")
            cfg = await get_config(guild_id)
            now = int(time.time())
            marriage_id = str(uuid.uuid4())
            record = {
                "id": marriage_id,
                "guild_id": guild_id,
                "mode": mode,
                "required_count": MODE_REQUIRED_COUNT[mode],
                "participants": list(dict.fromkeys(participants)),  # dedupe, keep order
                "accepted": [creator_id],  # proposer implicitly consents by proposing
                "proposal_creator_id": creator_id,
                "status": "pending",
                "created_at": now,
                "expires_at": now + int(cfg["proposal_expiry"]),
                "activated_at": None,
            }
            marriages[marriage_id] = record
            await global_save_section("marriages", marriages)
            return record

    @staticmethod
    async def accept(guild_id: int, marriage_id: str, user_id: int) -> tuple[bool, str, Optional[dict]]:
        async with _lock_for(guild_id):
            marriages = await global_get_section("marriages")
            m = marriages.get(marriage_id)
            if not m or m["status"] != "pending":
                return False, "not_found", None
            if int(time.time()) > m["expires_at"]:
                m["status"] = "expired"
                await global_save_section("marriages", marriages)
                return False, "expired", None
            if user_id not in m["participants"]:
                return False, "not_a_participant", None
            if user_id in m["accepted"]:
                return False, "already_accepted", m
            m["accepted"].append(user_id)
            activated = False
            if set(m["accepted"]) == set(m["participants"]) and len(m["accepted"]) == m["required_count"]:
                m["status"] = "active"
                m["activated_at"] = int(time.time())
                activated = True
            await global_save_section("marriages", marriages)
            return True, "activated" if activated else "accepted", m

    @staticmethod
    async def reject(guild_id: int, marriage_id: str, user_id: int) -> tuple[bool, str, Optional[dict]]:
        async with _lock_for(guild_id):
            marriages = await global_get_section("marriages")
            m = marriages.get(marriage_id)
            if not m or m["status"] != "pending":
                return False, "not_found", None
            if user_id not in m["participants"]:
                return False, "not_a_participant", None
            m["status"] = "rejected"
            m["rejected_by"] = user_id
            await global_save_section("marriages", marriages)
            return True, "rejected", m

    @staticmethod
    async def cancel(guild_id: int, marriage_id: str, user_id: int) -> tuple[bool, str, Optional[dict]]:
        async with _lock_for(guild_id):
            marriages = await global_get_section("marriages")
            m = marriages.get(marriage_id)
            if not m or m["status"] != "pending":
                return False, "not_found", None
            if m["proposal_creator_id"] != user_id:
                return False, "not_creator", None
            m["status"] = "cancelled"
            await global_save_section("marriages", marriages)
            return True, "cancelled", m

    @staticmethod
    async def get_active_for_user(guild_id: int, user_id: int) -> Optional[dict]:
        marriages = await global_get_section("marriages")
        _, m = _active_marriage_for(marriages, guild_id, user_id)
        return m

    @staticmethod
    async def start_divorce(guild_id: int, marriage_id: str, requester_id: int, reason: str) -> tuple[bool, str, Optional[dict]]:
        async with _lock_for(guild_id):
            marriages = await global_get_section("marriages")
            m = marriages.get(marriage_id)
            if not m or m["status"] != "active":
                return False, "not_active", None
            divorces = await global_get_section("marriage_divorces")
            for d in divorces.values():
                if d["marriage_id"] == marriage_id and d["status"] == "pending":
                    return False, "already_pending", None
            if requester_id not in m["participants"]:
                return False, "not_a_participant", None
            cfg = await get_config(guild_id)
            case_id = str(uuid.uuid4())
            now = int(time.time())
            case = {
                "id": case_id,
                "marriage_id": marriage_id,
                "guild_id": guild_id,
                "requester_id": requester_id,
                "reason": reason or None,
                "status": "pending",
                "judge_id": None,
                "decision": None,
                "created_at": now,
                "expires_at": now + int(cfg["divorce_expiry"]),
                "decided_at": None,
            }
            divorces[case_id] = case
            await global_save_section("marriage_divorces", divorces)
            return True, "created", case

    @staticmethod
    async def judge_decide(guild_id: int, case_id: str, judge_id: int, approve: bool, involved_can_judge: bool) -> tuple[bool, str, Optional[dict]]:
        async with _lock_for(guild_id):
            divorces = await global_get_section("marriage_divorces")
            case = divorces.get(case_id)
            if not case or case["status"] != "pending":
                return False, "not_found", None
            if int(time.time()) > case["expires_at"]:
                case["status"] = "expired"
                await global_save_section("marriage_divorces", divorces)
                return False, "expired", None
            marriages = await global_get_section("marriages")
            marriage = marriages.get(case["marriage_id"])
            if marriage and judge_id in marriage["participants"] and not involved_can_judge:
                return False, "involved_spouse", None
            case["judge_id"] = judge_id
            case["decision"] = "approved" if approve else "rejected"
            case["status"] = "decided"
            case["decided_at"] = int(time.time())
            await global_save_section("marriage_divorces", divorces)
            if approve and marriage:
                marriage["status"] = "divorced"
                marriage["archived_at"] = int(time.time())
                await global_save_section("marriages", marriages)
            return True, case["decision"], case

    @staticmethod
    async def cancel_divorce(guild_id: int, case_id: str, user_id: int) -> tuple[bool, str]:
        async with _lock_for(guild_id):
            divorces = await global_get_section("marriage_divorces")
            case = divorces.get(case_id)
            if not case or case["status"] != "pending":
                return False, "not_found"
            if case["requester_id"] != user_id:
                return False, "not_requester"
            case["status"] = "cancelled"
            await global_save_section("marriage_divorces", divorces)
            return True, "cancelled"


def is_judge(member: discord.Member, cfg: dict) -> bool:
    if cfg.get("judge_role_id"):
        return any(r.id == cfg["judge_role_id"] for r in member.roles)
    return member.guild_permissions.moderate_members or any(
        r.name.lower() in JUDGE_ROLE_NAMES for r in member.roles
    )


# ── Proposal view (Accept / Reject / Cancel) ──────────────────────────────────

class ProposalView(discord.ui.View):
    def __init__(self, guild_id: int, marriage_id: str, participants: list[int], creator_id: int):
        super().__init__(timeout=PROPOSAL_EXPIRY_SECONDS)
        self.guild_id = guild_id
        self.marriage_id = marriage_id
        self.participants = set(participants)
        self.creator_id = creator_id

    async def _refresh_embed(self, interaction: discord.Interaction, m: dict, extra_note: str = ""):
        accepted = set(m["accepted"])
        lines = []
        for uid in m["participants"]:
            mark = "✅" if uid in accepted else "⏳"
            lines.append(f"{mark} <@{uid}>")
        embed = (EmbedBuilder(color=Palette.SUCCESS if m["status"] == "active" else Palette.PRIMARY)
                 .title(f"{MODE_LABEL.get(m['mode'], 'Marriage Proposal')}")
                 .description(
                     f"Proposed by <@{m['proposal_creator_id']}>\n\n"
                     + "\n".join(lines)
                     + (f"\n\n{extra_note}" if extra_note else "")
                 )
                 .footer(f"Status: {m['status']}").build())
        if m["status"] in ("active", "rejected", "cancelled", "expired"):
            for child in self.children:
                child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="marry_accept")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.participants:
            return await interaction.response.send_message(
                "This proposal isn't addressed to you.", ephemeral=True
            )
        ok, reason, m = await MarriageDB.accept(self.guild_id, self.marriage_id, interaction.user.id)
        if not ok:
            msg = {
                "not_found": "This proposal is no longer active.",
                "expired": "This proposal has expired.",
                "not_a_participant": "You aren't part of this proposal.",
                "already_accepted": "You've already accepted this proposal.",
            }.get(reason, "Couldn't process that.")
            return await interaction.response.send_message(msg, ephemeral=True)
        note = "🎉 Everyone has accepted — the marriage is now active!" if reason == "activated" else f"<@{interaction.user.id}> accepted!"
        await self._refresh_embed(interaction, m, note)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="marry_reject")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.participants:
            return await interaction.response.send_message(
                "This proposal isn't addressed to you.", ephemeral=True
            )
        ok, reason, m = await MarriageDB.reject(self.guild_id, self.marriage_id, interaction.user.id)
        if not ok:
            return await interaction.response.send_message("This proposal is no longer active.", ephemeral=True)
        await self._refresh_embed(interaction, m, f"💔 <@{interaction.user.id}> rejected the proposal.")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="marry_cancel")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.creator_id:
            return await interaction.response.send_message(
                "Only the person who made the proposal can cancel it.", ephemeral=True
            )
        ok, reason, m = await MarriageDB.cancel(self.guild_id, self.marriage_id, interaction.user.id)
        if not ok:
            return await interaction.response.send_message("This proposal is no longer active.", ephemeral=True)
        await self._refresh_embed(interaction, m, "🚫 Proposal cancelled.")


class DivorceView(discord.ui.View):
    def __init__(self, guild_id: int, case_id: str, requester_id: int):
        super().__init__(timeout=DIVORCE_EXPIRY_SECONDS)
        self.guild_id = guild_id
        self.case_id = case_id
        self.requester_id = requester_id

    async def _resolve(self, interaction: discord.Interaction, approve: bool):
        cfg = await get_config(self.guild_id)
        member = interaction.user
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        if not is_judge(member, cfg):
            return await interaction.response.send_message(
                "You don't have permission to judge this case.", ephemeral=True
            )
        ok, decision, case = await MarriageDB.judge_decide(
            self.guild_id, self.case_id, member.id, approve, involved_can_judge=False
        )
        if not ok:
            msg = {
                "not_found": "This case is no longer pending.",
                "expired": "This divorce case has expired.",
                "involved_spouse": "A spouse in this marriage can't judge their own case.",
            }.get(decision, "Couldn't process that.")
            return await interaction.response.send_message(msg, ephemeral=True)
        for child in self.children:
            child.disabled = True
        result = "✅ Divorce **approved** — the marriage has been archived." if decision == "approved" else "❌ Divorce **rejected** — the marriage remains active."
        embed = (EmbedBuilder(color=Palette.SUCCESS if decision == "approved" else Palette.DANGER)
                 .title("⚖️ Divorce Case Decided")
                 .description(f"{result}\n\nJudged by {member.mention}").build())
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Approve Divorce", style=discord.ButtonStyle.danger, custom_id="divorce_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, approve=True)

    @discord.ui.button(label="Reject Divorce", style=discord.ButtonStyle.success, custom_id="divorce_reject")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, approve=False)

    @discord.ui.button(label="Cancel Case", style=discord.ButtonStyle.secondary, custom_id="divorce_cancel")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message(
                "Only the person who filed can cancel this case.", ephemeral=True
            )
        ok, _ = await MarriageDB.cancel_divorce(self.guild_id, self.case_id, interaction.user.id)
        if not ok:
            return await interaction.response.send_message("This case is no longer pending.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        embed = EmbedBuilder(color=Palette.INFO).title("Case Cancelled").description("The divorce case was withdrawn.").build()
        await interaction.response.edit_message(embed=embed, view=self)


# ── Cog ────────────────────────────────────────────────────────────────────

ACTIONS = {
    "kiss": {"verb": "kisses", "emoji": "💋", "self_msg": "You can't kiss yourself... or can you? Pick someone else!"},
    "hug": {"verb": "gives a warm hug to", "emoji": "🤗", "self_msg": "Aww, self-hugs are nice, but pick a friend to hug!"},
    "kill": {"verb": "dramatically defeats", "emoji": "⚔️", "self_msg": "You can't duel yourself! Pick an opponent.",
              "suffix": " in a video-game-style duel — they respawn safely a moment later. 🎮"},
    "nom": {"verb": "playfully noms", "emoji": "😋", "self_msg": "You can't nom yourself! Pick a snack— I mean, a friend."},
    "lick": {"verb": "gives a playful lick to", "emoji": "👅", "self_msg": "Can't lick yourself, pick someone else!",
              "consent_note": "*(If you'd rather not be licked, just let them know! 😅)*"},
    "tickle": {"verb": "tickles", "emoji": "🤭", "self_msg": "Ticking yourself doesn't really work, does it? Pick a friend!"},
    "touches": {"verb": "gives a friendly high-five to", "emoji": "🙌", "self_msg": "High-five yourself? Try picking a friend!"},
    "griddy": {"verb": "beats", "emoji": "🕺", "self_msg": "Can't griddy on yourself! Pick an opponent.",
                "suffix": " in a friendly cartoon showdown, then hits the Griddy in celebration! 🕺💃"},
}


class MarriageSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.action_cd = CooldownMap(default_ttl=ACTION_COOLDOWN_SECONDS)

    # ── Interaction commands ────────────────────────────────────────────────
    async def _do_action(self, interaction: discord.Interaction, action: str, user: discord.Member):
        cfg = ACTIONS[action]
        actor = interaction.user

        if user.id == actor.id:
            return await interaction.response.send_message(cfg["self_msg"], ephemeral=True)
        if user.id == self.bot.user.id:
            return await interaction.response.send_message(
                "I appreciate the thought, but let's pick a human friend instead!", ephemeral=True
            )
        if user.bot:
            return await interaction.response.send_message(
                "That user is a bot — try picking a real member!", ephemeral=True
            )

        if not self.action_cd.check(actor.id):
            remaining = self.action_cd.remaining(actor.id)
            return await interaction.response.send_message(
                f"Slow down! Try again in {remaining:.0f}s.", ephemeral=True
            )

        desc = f"{cfg['emoji']} **{actor.display_name}** {cfg['verb']} **{user.display_name}**!"
        desc += cfg.get("suffix", "")
        if cfg.get("consent_note"):
            desc += f"\n\n{cfg['consent_note']}"

        embed = (EmbedBuilder(color=Palette.PRIMARY)
                 .description(desc)
                 .footer("Barm assistant 🐴").build())
        try:
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            if not interaction.response.is_done():
                await interaction.response.send_message(desc)

    def _register_action(self, name: str, description: str):
        @app_commands.command(name=name, description=description)
        @app_commands.describe(user="Who to target")
        async def _cmd(interaction: discord.Interaction, user: discord.Member):
            await self._do_action(interaction, name, user)
        _cmd.name = name
        return _cmd

    # ── /marry group ────────────────────────────────────────────────────────
    marry = app_commands.Group(name="marry", description="Fictional marriage system commands")

    @marry.command(name="propose", description="Propose a two-person (halal) marriage to another user")
    @app_commands.describe(user="Who you're proposing to")
    async def propose(self, interaction: discord.Interaction, user: discord.Member):
        await self._start_proposal(interaction, "two_person", [interaction.user.id, user.id])

    @marry.command(name="group", description="Propose a 3- or 4-person harem marriage")
    @app_commands.describe(
        size="Final group size (3 or 4, including you)",
        user1="First person to propose to", user2="Second person to propose to",
        user3="Third person to propose to (only for size 4)",
    )
    @app_commands.choices(size=[
        app_commands.Choice(name="3 (trio)", value=3),
        app_commands.Choice(name="4 (squad)", value=4),
    ])
    async def group(
        self, interaction: discord.Interaction, size: app_commands.Choice[int],
        user1: discord.Member, user2: discord.Member, user3: Optional[discord.Member] = None,
    ):
        needed = size.value
        targets = [user1, user2] + ([user3] if user3 else [])
        if len(targets) != needed - 1:
            return await interaction.response.send_message(
                f"A size-{needed} marriage needs exactly {needed - 1} other people. You gave {len(targets)}.",
                ephemeral=True,
            )
        mode = "three_person" if needed == 3 else "four_person"
        await self._start_proposal(interaction, mode, [interaction.user.id] + [t.id for t in targets])

    async def _start_proposal(self, interaction: discord.Interaction, mode: str, participant_ids: list[int]):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This must be used in a server.", ephemeral=True)

        cfg = await get_config(guild.id)
        if not cfg["enabled"]:
            return await interaction.response.send_message("Marriage features are disabled on this server.", ephemeral=True)
        if mode not in cfg["allowed_modes"]:
            return await interaction.response.send_message("That marriage mode isn't allowed on this server.", ephemeral=True)

        if len(set(participant_ids)) != len(participant_ids):
            return await interaction.response.send_message("You can't propose to the same person twice.", ephemeral=True)

        for uid in participant_ids:
            member = guild.get_member(uid)
            if member is None:
                return await interaction.response.send_message("All participants must be members of this server.", ephemeral=True)
            if member.bot and not cfg["allow_bots"]:
                return await interaction.response.send_message("Bots can't participate in marriages here.", ephemeral=True)

        async with _lock_for(guild.id):
            marriages = await global_get_section("marriages")
            for uid in participant_ids:
                mid, _ = _active_marriage_for(marriages, guild.id, uid)
                if mid:
                    return await interaction.response.send_message(
                        f"<@{uid}> is already in an active marriage.", ephemeral=True
                    )
            mid, _ = _active_proposal_involving(marriages, guild.id, set(participant_ids))
            if mid:
                return await interaction.response.send_message(
                    "One or more of these users already has a pending proposal.", ephemeral=True
                )

        record = await MarriageDB.create_proposal(guild.id, mode, interaction.user.id, participant_ids)

        lines = [f"⏳ <@{uid}>" if uid != interaction.user.id else f"✅ <@{uid}> (proposer)" for uid in participant_ids]
        embed = (EmbedBuilder(color=Palette.PRIMARY)
                 .title(f"💌 Marriage Proposal — {MODE_LABEL[mode]}")
                 .description(
                     f"<@{interaction.user.id}> has proposed!\n\n" + "\n".join(lines) +
                     f"\n\nAll participants must click **Accept**. This proposal expires <t:{record['expires_at']}:R>."
                 ).build())
        view = ProposalView(guild.id, record["id"], participant_ids, interaction.user.id)
        await interaction.response.send_message(
            content=" ".join(f"<@{uid}>" for uid in participant_ids if uid != interaction.user.id),
            embed=embed, view=view,
        )

    @marry.command(name="status", description="View your current marriage, or another user's")
    @app_commands.describe(user="Whose marriage to check (defaults to you)")
    async def status(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This must be used in a server.", ephemeral=True)
        m = await MarriageDB.get_active_for_user(guild.id, target.id)
        if not m:
            return await interaction.response.send_message(f"{target.display_name} isn't currently married.", ephemeral=True)
        members = "\n".join(f"• <@{uid}>" for uid in m["participants"])
        embed = (EmbedBuilder(color=Palette.SUCCESS)
                 .title(MODE_LABEL[m["mode"]])
                 .description(f"{members}\n\nMarried since <t:{m['activated_at']}:D>").build())
        await interaction.response.send_message(embed=embed)

    @marry.command(name="members", description="List every participant in a marriage")
    @app_commands.describe(user="Any participant of the marriage to look up")
    async def members(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await self.status(interaction, user)

    @marry.command(name="divorce", description="Start a divorce case for your marriage")
    @app_commands.describe(reason="Optional reason for the record")
    async def divorce(self, interaction: discord.Interaction, reason: Optional[str] = None):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This must be used in a server.", ephemeral=True)
        m = await MarriageDB.get_active_for_user(guild.id, interaction.user.id)
        if not m:
            return await interaction.response.send_message("You aren't currently married.", ephemeral=True)
        ok, reason_code, case = await MarriageDB.start_divorce(guild.id, m["id"], interaction.user.id, reason or "")
        if not ok:
            msg = {"already_pending": "A divorce case is already pending for this marriage."}.get(
                reason_code, "Couldn't start a divorce case."
            )
            return await interaction.response.send_message(msg, ephemeral=True)

        embed = (EmbedBuilder(color=Palette.WARNING)
                 .title("⚖️ Divorce Case Filed")
                 .description(
                     f"<@{interaction.user.id}> has requested a divorce.\n"
                     + (f"Reason: {reason}\n" if reason else "")
                     + f"\nA judge (server moderator) needs to review this case. Expires <t:{case['expires_at']}:R>."
                 ).build())
        view = DivorceView(guild.id, case["id"], interaction.user.id)
        await interaction.response.send_message(
            content=" ".join(f"<@{uid}>" for uid in m["participants"] if uid != interaction.user.id),
            embed=embed, view=view,
        )
        cfg = await get_config(guild.id)
        if cfg.get("log_channel_id"):
            ch = guild.get_channel(cfg["log_channel_id"])
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    @marry.command(name="cancel", description="Cancel a proposal you created")
    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Use the **Cancel** button on your original proposal message to withdraw it.", ephemeral=True
        )

    @marry.command(name="config", description="[Admin] Configure the marriage system for this server")
    @app_commands.describe(
        enabled="Turn the marriage system on/off",
        allow_bots="Allow bots as marriage participants",
        judge_role="Role allowed to judge divorce cases",
        log_channel="Channel to log divorce filings to",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_cmd(
        self, interaction: discord.Interaction,
        enabled: Optional[bool] = None, allow_bots: Optional[bool] = None,
        judge_role: Optional[discord.Role] = None, log_channel: Optional[discord.TextChannel] = None,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This must be used in a server.", ephemeral=True)
        updates = {}
        if enabled is not None:
            updates["enabled"] = enabled
        if allow_bots is not None:
            updates["allow_bots"] = allow_bots
        if judge_role is not None:
            updates["judge_role_id"] = judge_role.id
        if log_channel is not None:
            updates["log_channel_id"] = log_channel.id
        cfg = await set_config(guild.id, **updates) if updates else await get_config(guild.id)
        embed = (EmbedBuilder(color=Palette.INFO)
                 .title("💍 Marriage System Config")
                 .field("Enabled", str(cfg["enabled"]))
                 .field("Bots allowed", str(cfg["allow_bots"]))
                 .field("Judge role", f"<@&{cfg['judge_role_id']}>" if cfg["judge_role_id"] else "Mods (Moderate Members)")
                 .field("Log channel", f"<#{cfg['log_channel_id']}>" if cfg["log_channel_id"] else "None")
                 .build())
        await interaction.response.send_message(embed=embed, ephemeral=True)



bot = CommunityBot()
tree = bot.tree
install_error_handler(tree)

@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    if await sync_guild_safely(bot, guild): print(f"✅ Synced commands to new guild: {guild.name}")
    else: print(f"⚠️  Failed to sync to {guild.name}")

# ── IMAGE GENERATION ─────────────────────────────────────────────────────────




def _make_quote_card(*, quote_text: str, author_name: str, quoted_by: str, stars: int, avatar_bytes: bytes | None) -> discord.File:
    W, H, PAD = 1100, 420, 44
    AV_SIZE = 168
    AV_X = 48
    AV_Y = (H - AV_SIZE) // 2

    BLURPLE  = (88, 101, 242)
    GREEN    = (35, 165, 90)
    SURFACE  = (43, 45, 49)
    SURFACE2 = (35, 36, 40)
    WHITE    = (242, 243, 245)
    MUTED    = (181, 186, 193)
    DIM      = (116, 122, 130)

    img = Image.new("RGBA", (W, H), (*SURFACE, 255))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, (W, H), SURFACE, SURFACE2, direction="horizontal")
    draw_starfield(draw, (W, H), count=55, seed=7, brightness_range=(42, 82))
    draw.rectangle([(0, 0), (8, H)], fill=(*BLURPLE, 255))
    draw.rounded_rectangle([(28, 28), (W - 28, H - 28)], radius=22, outline=(255, 255, 255, 24), width=1)

    TEXT_X = AV_X + AV_SIZE + PAD
    RING = 6
    draw.ellipse([AV_X - RING, AV_Y - RING, AV_X + AV_SIZE + RING, AV_Y + AV_SIZE + RING], fill=(*BLURPLE, 70), outline=(*BLURPLE, 220), width=3)
    
    if avatar_bytes:
        try:
            av = circular_avatar(avatar_bytes, AV_SIZE)
            img.paste(av, (AV_X, AV_Y), av)
        except Exception:
            draw.ellipse([(AV_X, AV_Y), (AV_X + AV_SIZE, AV_Y + AV_SIZE)], fill=(*SURFACE2, 255), outline=(*BLURPLE, 160), width=2)
    else:
        draw.ellipse([(AV_X, AV_Y), (AV_X + AV_SIZE, AV_Y + AV_SIZE)], fill=(*SURFACE2, 255), outline=(*BLURPLE, 160), width=2)

    fnt_kicker   = load_font("bold", 16)
    fnt_bigquote = load_font("italic", 96)
    fnt_quote    = load_font("italic", 34)
    fnt_author   = load_font("bold", 26)
    fnt_handle   = load_font("regular", 18)
    fnt_footer   = load_font("regular", 15)

    draw.rounded_rectangle([(TEXT_X, 42), (TEXT_X + 170, 70)], radius=14, fill=(*BLURPLE, 70), outline=(*BLURPLE, 140), width=1)
    draw_text_with_fallback(draw, (TEXT_X + 16, 47), "QUOTE CAPTURED", fnt_kicker, (*MUTED, 255))
    draw.ellipse([(AV_X + AV_SIZE - 28, AV_Y + AV_SIZE - 28), (AV_X + AV_SIZE + 4, AV_Y + AV_SIZE + 4)], fill=(*SURFACE, 255))
    draw.ellipse([(AV_X + AV_SIZE - 23, AV_Y + AV_SIZE - 23), (AV_X + AV_SIZE - 1, AV_Y + AV_SIZE - 1)], fill=(*GREEN, 255))

    TEXT_W = W - TEXT_X - PAD
    quote_text = quote_text.strip() or "*[no text]*"
    lines = wrap_text_pixels(draw, quote_text, fnt_quote, TEXT_W - 28, max_lines=5)

    draw_text_with_fallback(draw, (TEXT_X - 12, 78), "\u201c", fnt_bigquote, (*BLURPLE, 110))
    LINE_H, TEXT_Y0 = 45, 112
    for i, line in enumerate(lines):
        draw_text_with_fallback(draw, (TEXT_X + 4, TEXT_Y0 + i * LINE_H), line, fnt_quote, (*WHITE, 255))

    text_bottom = TEXT_Y0 + len(lines) * LINE_H
    draw_text_with_fallback(draw, (W - PAD - 20, text_bottom - 24), "\u201d", fnt_bigquote, (*BLURPLE, 100), anchor="ra")

    author_y = max(text_bottom + 14, H - 104)
    draw.rectangle([(TEXT_X, author_y + 10), (TEXT_X + 20, author_y + 13)], fill=(*BLURPLE, 255))
    author_text = truncate_text_pixels(draw, author_name, fnt_author, TEXT_W - 38)
    handle_raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in author_name).strip("_") or "user"
    handle = truncate_text_pixels(draw, f"@{handle_raw}", fnt_handle, TEXT_W - 38)
    draw_text_with_fallback(draw, (TEXT_X + 30, author_y), author_text, fnt_author, (*WHITE, 255))
    draw_text_with_fallback(draw, (TEXT_X + 30, author_y + 32), handle, fnt_handle, (*MUTED, 220))

    sep_y = H - 42
    draw.line([(TEXT_X, sep_y), (W - PAD, sep_y)], fill=(255, 255, 255, 30), width=1)
    footer = truncate_text_pixels(draw, f"Quoted by {quoted_by}  •  {stars} ⭐  •  Barm Assistant", fnt_footer, TEXT_W)
    draw_text_with_fallback(draw, (TEXT_X, sep_y + 10), footer, fnt_footer, (*DIM, 230))
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(*BLURPLE, 90), width=1)

    return to_discord_file(img, filename="quote.png")

def _quote_fallback_message(author_name: str, quote_text: str, quoted_by_mention: str) -> str:
    safe_author = discord.utils.escape_markdown(author_name)
    safe_quote = discord.utils.escape_markdown(quote_text.strip() or "*[no text]*")
    safe_quote = safe_quote.replace("\n", "\n> ")
    if len(safe_quote) > 1500:
        safe_quote = safe_quote[:1497].rstrip() + "..."
    return f"✨ **{safe_author}**\n> {safe_quote}\n📌 Quoted by {quoted_by_mention}"

# ── ACTION GIFS ──────────────────────────────────────────────────────────────
_ACTION_GIFS = {
    "hug": ["https://media.tenor.com/i_7Sb0Z2ZJ8AAAAC/anime-hug.gif", "https://media.tenor.com/XaFRgCRk2hAAAAAC/hug-anime.gif"],
    "highfive": ["https://media.tenor.com/oAnN2O2UkHkAAAAC/high-five-anime.gif"],
    "slap": ["https://media.tenor.com/0omJP64mlA4AAAAC/anime-slap.gif"],
    "kill": ["https://media.tenor.com/1T2q0JnT2dcAAAAC/anime-kill.gif"],
    "handshake": ["https://media.tenor.com/L4-jT-JEjCYAAAAC/handshake-anime.gif"],
}
_ACTION_META = {
    "hug": {"emoji": "🤗", "color": 0xFF69B4, "verb": "hugs", "desc": "Warm anime hug incoming~"},
    "highfive": {"emoji": "🙌", "color": 0xFFD700, "verb": "high-fives", "desc": "Slap those hands together!"},
    "slap": {"emoji": "👋", "color": 0xFF4500, "verb": "slaps", "desc": "The wind-up... the swing..."},
    "kill": {"emoji": "⚔️", "color": 0x8B0000, "verb": "kills", "desc": "Moment of silence 🕯️"},
    "handshake": {"emoji": "🤝", "color": 0x00CED1, "verb": "shakes", "desc": "A deal has been struck."},
    "poke": {"emoji": "👉", "color": 0x9B59B6, "verb": "pokes", "desc": "Boop!"},
    "pat": {"emoji": "🫳", "color": 0xFFB7C5, "verb": "pats", "desc": "There, there..."},
    "bite": {"emoji": "🦷", "color": 0xE74C3C, "verb": "bites", "desc": "Nom!"},
}
_ACTION_KEYWORDS = {
    "hug": "hug", "highfive": "highfive", "high five": "highfive", "high-five": "highfive",
    "slap": "slap", "kill": "kill", "handshake": "handshake", "poke": "poke", "pat": "pat", "bite": "bite",
}

async def _send_action_embed(channel, actor, target, action, *, from_slash=False):
    meta = _ACTION_META.get(action)
    if not meta: return
    gifs = _ACTION_GIFS.get(action, [])
    if not gifs: return

    gif = random.choice(gifs)
    text = f"{actor.mention} {meta['verb']} {target.mention}!"
    embed = (EmbedBuilder(color=meta["color"])
        .description(f"## {meta['emoji']} {text}\n{meta['desc']}")
        .image(gif).footer(f"Requested by {actor.display_name}").build())

    if from_slash: await channel.followup.send(embed=embed)
    else: await channel.send(embed=embed)

_BOT_ALIASES = ("barm assistant", "sayori", "nokotan", "bocchi", "haru urara")

def _bot_addressed(message: discord.Message) -> bool:
    if bot.user in message.mentions: return True
    lc = message.content.lower()
    return any(alias in lc for alias in _BOT_ALIASES)

def _detect_action(content_lower: str) -> str | None:
    for keyword, action in _ACTION_KEYWORDS.items():
        if keyword in content_lower: return action
    return None

def _find_action_target(message: discord.Message) -> discord.User | None:
    mentions = [u for u in message.mentions if u.id != bot.user.id]
    target = next((u for u in mentions if u.id != message.author.id), None)
    if target: return target
    return next((u for u in mentions), None)

# ── MESSAGE PIPELINE ─────────────────────────────────────────────────────────
@bot.event
async def on_message(message: discord.Message) -> None:
    if message.guild and not message.author.bot:
        if await _handle_counting_message(message): return
    if not message.guild:
        await _handle_dm_quote(message)
        return
    await _handle_guild_message(message)

async def _handle_guild_message(message: discord.Message) -> None:
    if message.author.bot: return
    author = message.author
    guild = message.guild
    key = (guild.id, author.id)

    if bot.user in message.mentions and "potato" in message.content.lower():
        try: await message.add_reaction("🥔")
        except discord.HTTPException: pass

    if _bot_addressed(message):
        content_lower = message.content.lower()
        action = _detect_action(content_lower)
        target = _find_action_target(message)
        if action and target:
            await _send_action_embed(message.channel, author, target, action)

    if bot.xp_cd.check(key, ttl=60):
        await _award_chat_sayories(message, random.randint(5, 10))
    if bot.chat_cd.check(key, ttl=60):
        await g_eco_add(author.id, 2)
    if bot.bocchi_cd.check(key, ttl=120):
        gain = 1 if random.random() < 0.6 else 0
        await _award_chat_bocchies(message, gain)

    await _handle_drop_event(message)
    await _handle_word_tracker(message)
    await _handle_reply_quote(message)

async def _award_chat_sayories(message: discord.Message, gain: int) -> None:
    author = message.author
    old_bal = await g_eco_get(author.id)
    old_tier = tier_from_xp(old_bal)
    new_bal = await g_eco_add(author.id, gain)
    new_tier = tier_from_xp(new_bal)

    if new_tier > old_tier and new_tier >= 1:
        await _announce_tier_up(message, new_tier, new_bal)

async def _announce_tier_up(message: discord.Message, tier: int, balance: int) -> None:
    author = message.author
    await assign_tier_role(author, tier)
    emoji = TIER_EMOJIS.get(tier, "⬆️")
    title = TIER_TITLES.get(tier, f"Tier {tier}")
    color = TIER_COLORS.get(tier, 0xFFFFFF)
    _, into, needed = xp_for_next_tier(balance)
    bar = progress_bar(into, needed)

    max_tier_note = ("*You have reached the pinnacle — **Tier 25: Sayorie Legend**!* 🌟" if tier >= 25 else f"*You've been granted the **Level {tier}** role!*")
    
    embed = (EmbedBuilder(color=color)
        .title(f"{emoji} Tier Up! → **Tier {tier}**")
        .description(f"### 🎉 Congratulations, {author.mention}!\n\nYou have ascended to **Tier {tier} — {title}** {emoji}\n\n**Sayories Progress:** {bar}\n`{into:,}` / `{needed:,}` Sayories to next tier\n\n{max_tier_note}")
        .thumbnail(author.display_avatar.url).footer(f"Barm assistant Tier System • Total Sayories: {balance:,}").build())
    await message.channel.send(embed=embed)

async def _award_chat_bocchies(message: discord.Message, gain: int) -> None:
    author = message.author
    guild = message.guild
    old_points = await bocchi_get(guild.id, author.id)
    old_rank = bocchi_rank_from_points(old_points)
    new_points = await bocchi_add(guild.id, author.id, gain)
    new_rank = bocchi_rank_from_points(new_points)

    if new_rank > old_rank and new_rank >= 1:
        await bocchi_assign_rank_role(author, new_rank)
        await _announce_bocchi_rank_up(message, new_rank, new_points)

async def _announce_bocchi_rank_up(message: discord.Message, rank: int, points: int) -> None:
    author = message.author
    n_emoji = BOCCHI_RANK_EMOJIS.get(rank, "🌸")
    n_title = BOCCHI_RANK_TITLES.get(rank, f"Tier {rank}")
    n_color = BOCCHI_RANK_COLORS.get(rank, 0xFF69B4)
    _, n_into, n_needed = bocchi_progress(points)
    n_bar = progress_bar(n_into, n_needed)

    is_max = rank >= 10
    embed = (EmbedBuilder(color=n_color)
        .title(f"{n_emoji} Bocchi Tier Up! → **Tier {rank}**")
        .description(f"### 🎀 Well done, {author.mention}!\n\nYou have reached **Tier {rank} — {n_title}** {n_emoji}\n\n**Bocchies Progress:** {n_bar}\n" + (f"`{n_into:,}` / `{n_needed:,}` Bocchies to next rank\n\n" if not is_max else "\n") + ("*You are the **Bocchi Legend** of this server!* 💗" if is_max else f"*You've been granted the **Tier {rank}** role in this server!*"))
        .thumbnail(author.display_avatar.url).footer(f"Barm assistant 🔥 Bocchies • This server only • Total: {points:,}").build())
    await message.channel.send(embed=embed)

async def _handle_drop_event(message: discord.Message) -> None:
    gid = message.guild.id
    bot._msg_count[gid] = bot._msg_count.get(gid, 0) + 1
    threshold_key = f"drop_threshold_{gid}"
    if threshold_key not in bot._msg_count:
        bot._msg_count[threshold_key] = bot._msg_count[gid] + random.randint(30, 100)

    active_key = f"drop_active_{gid}"
    amount_key = f"drop_amount_{gid}"

    if bot._msg_count.get(active_key, False):
        if message.content.strip().lower() == "claim":
            bot._msg_count[active_key] = False
            bot._msg_count[threshold_key] = bot._msg_count[gid] + random.randint(30, 100)
            drop_amount = bot._msg_count.get(amount_key, 100)
            new_bal = await g_eco_add(message.author.id, drop_amount)
            embed = (EmbedBuilder(color=Palette.SAYORIES).description(f"🏆 **{message.author.display_name}** claimed the bonus and got **+{drop_amount} Sayories!**\n💰 New balance: **{new_bal:,} Sayories**").footer("Barm assistant 🐴 • Haru Urara is watching").build())
            await message.channel.send(embed=embed)
        return

    if bot._msg_count[gid] >= bot._msg_count[threshold_key]:
        bot._msg_count[active_key] = True
        drop_amount = random.choice([50, 75, 100, 150, 200])
        bot._msg_count[amount_key] = drop_amount
        embed = (EmbedBuilder(color=Palette.SAYORIES).description(f"💎 A bonus Sayories drop has appeared! First person to type `claim` wins **+{drop_amount} Sayories!**").footer("Barm assistant 🐴 • Haru Urara is watching").build())
        await message.channel.send(embed=embed)

async def _handle_word_tracker(message: discord.Message) -> None:
    watched = await db_get_section(message.guild.id, "word_tracker")
    if not watched: return
    words_in_msg = message.content.lower().split()
    counts = await db_get_section(message.guild.id, "word_counts")
    uid_str = str(message.author.id)
    changed = False
    for word in watched:
        if word in words_in_msg:
            counts.setdefault(word, {})
            counts[word][uid_str] = counts[word].get(uid_str, 0) + words_in_msg.count(word)
            changed = True
    if changed: await db_save_section(message.guild.id, "word_counts", counts)

async def _handle_reply_quote(message: discord.Message) -> None:
    if message.reference is None or not _bot_addressed(message): return
    content_stripped = message.content.lower().replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "")
    for alias in _BOT_ALIASES: content_stripped = content_stripped.replace(alias, "")
    content_stripped = content_stripped.strip()
    if "quote" not in content_stripped: return

    try: ref = await message.channel.fetch_message(message.reference.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException): return

    if not ref or ref.author.id == message.author.id: return
    await _process_quote(message, ref)

async def _process_quote(trigger_msg: discord.Message, ref: discord.Message) -> None:
    quotes = await global_get_section("quotes")
    quid = str(ref.author.id)
    quotes.setdefault(quid, {"stars": 0})
    quotes[quid]["stars"] += 1
    await global_save_section("quotes", quotes)
    new_stars = quotes[quid]["stars"]

    raw_text = ref.content or "*[no text]*"
    quote_text = resolve_mentions(raw_text, guild=trigger_msg.guild)

    import time
    qhist = await global_get_section("quote_history")
    qhist.setdefault(quid, [])
    qhist[quid].insert(0, {
        "text": quote_text,
        "quoter": trigger_msg.author.display_name,
        "timestamp": int(time.time())
    })
    qhist[quid] = qhist[quid][:100]
    await global_save_section("quote_history", qhist)
    try: av_bytes = await ref.author.display_avatar.with_size(256).read()
    except (discord.HTTPException, discord.Forbidden): av_bytes = None

    try:
        quote_file = _make_quote_card(quote_text=quote_text, author_name=ref.author.display_name, quoted_by=trigger_msg.author.display_name, stars=new_stars, avatar_bytes=av_bytes)
        await trigger_msg.channel.send(file=quote_file)
    except Exception:
        await trigger_msg.channel.send(_quote_fallback_message(ref.author.display_name, quote_text, trigger_msg.author.mention))

    embed = (EmbedBuilder(color=Palette.QUOTE).description(f"⭐ **{trigger_msg.author.display_name}** quoted **{ref.author.display_name}**!\n**{ref.author.display_name}** now has **{new_stars} ⭐**").build())
    await trigger_msg.channel.send(embed=embed)

async def _handle_dm_quote(message: discord.Message) -> None:
    if message.author.bot: return
    if "quote" not in message.content.lower(): return
    if not message.reference:
        await message.channel.send("💡 **How to quote in DMs:** Reply to the message you want to quote, then include the word `quote` in your reply!")
        return
    try: ref = await message.channel.fetch_message(message.reference.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException): return

    if ref.author.id == message.author.id: await message.channel.send("💔 You can't quote yourself!", delete_after=5); return
    if ref.author.bot: await message.channel.send("🤖 You can't quote a bot.", delete_after=5); return
    if not ref.content and not ref.attachments: await message.channel.send("❌ That message has no text to quote.", delete_after=5); return

    quotes = await global_get_section("quotes")
    quid = str(ref.author.id)
    quotes.setdefault(quid, {"stars": 0})
    quotes[quid]["stars"] += 1
    await global_save_section("quotes", quotes)
    new_stars = quotes[quid]["stars"]

    quote_text = resolve_mentions(ref.content or "*[no text — see attachment]*")

    import time
    qhist = await global_get_section("quote_history")
    qhist.setdefault(quid, [])
    qhist[quid].insert(0, {
        "text": quote_text,
        "quoter": message.author.display_name,
        "timestamp": int(time.time())
    })
    qhist[quid] = qhist[quid][:100]
    await global_save_section("quote_history", qhist)
    try: av_bytes = await ref.author.display_avatar.with_size(256).read()
    except (discord.HTTPException, discord.Forbidden): av_bytes = None

    try:
        quote_file = _make_quote_card(quote_text=quote_text, author_name=ref.author.display_name, quoted_by=message.author.display_name, stars=new_stars, avatar_bytes=av_bytes)
        await message.channel.send(file=quote_file)
    except Exception:
        await message.channel.send(_quote_fallback_message(ref.author.display_name, quote_text, message.author.mention))

    embed = (EmbedBuilder(color=Palette.QUOTE).description(f"⭐ **{message.author.display_name}** quoted **{ref.author.display_name}**!\n**{ref.author.display_name}** now has **{new_stars} ⭐** globally").build())
    await message.channel.send(embed=embed)

# ── COUNTING CHANNEL SYSTEM ──────────────────────────────────────────────────
import re as _re
_ROMAN_VALUES = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]

def _to_roman(n: int) -> str:
    if n <= 0: return ""
    result = ""
    for value, numeral in _ROMAN_VALUES:
        while n >= value: result += numeral; n -= value
    return result

def _from_roman(s: str) -> int | None:
    s = s.strip().upper()
    pattern = _re.compile(r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
    if not pattern.match(s) or s == "": return None
    roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for j in range(len(s)):
        val = roman_map[s[j]]
        if j + 1 < len(s) and roman_map[s[j + 1]] > val: total -= val
        else: total += val
    return total if total > 0 else None

COUNTING_MODES = {
    "counting": {"label": "Normal", "emoji": "🔢"}, "letter": {"label": "Letters", "emoji": "🔤"},
    "2-counting": {"label": "×2", "emoji": "2️⃣"}, "hexadecimal": {"label": "Hex", "emoji": "🔣"},
    "5-counting": {"label": "×5", "emoji": "5️⃣"}, "100-counting": {"label": "×100", "emoji": "💯"},
    "10-counting": {"label": "×10", "emoji": "🔟"}, "decimals": {"label": "Decimals", "emoji": "🔸"},
    "binary": {"label": "Binary", "emoji": "01"}, "roman": {"label": "Roman", "emoji": "🏛️"},
}

def _next_count_value(mode: str, current: int | float) -> str:
    if mode == "counting": return str(int(current) + 1)
    elif mode == "letter":
        n = int(current) + 1
        result = ""
        while n > 0: n, rem = divmod(n - 1, 26); result = chr(65 + rem) + result
        return result
    elif mode == "2-counting": return str(int(current) + 2)
    elif mode == "hexadecimal": return hex(int(current) + 1)[2:].upper()
    elif mode == "5-counting": return str(int(current) + 5)
    elif mode == "100-counting": return str(int(current) + 100)
    elif mode == "10-counting": return str(int(current) + 10)
    elif mode == "decimals":
        n = round(current * 10) + 1
        whole, frac = divmod(n, 10)
        return f"{whole}.{frac}"
    elif mode == "binary": return bin(int(current) + 1)[2:]
    elif mode == "roman": return _to_roman(int(current) + 1)
    return str(int(current) + 1)

def _parse_count_input(mode: str, text: str) -> int | float | None:
    text = text.strip()
    try:
        if mode == "counting": return int(text)
        elif mode == "letter":
            text = text.upper()
            if not _re.fullmatch(r"[A-Z]+", text): return None
            val = 0
            for ch in text: val = val * 26 + (ord(ch) - 64)
            return val
        elif mode == "2-counting":
            v = int(text); return v if v % 2 == 0 else None
        elif mode == "hexadecimal": return int(text, 16)
        elif mode == "5-counting":
            v = int(text); return v if v % 5 == 0 else None
        elif mode == "100-counting":
            v = int(text); return v if v % 100 == 0 else None
        elif mode == "10-counting":
            v = int(text); return v if v % 10 == 0 else None
        elif mode == "decimals":
            if not _re.fullmatch(r"\d+\.\d", text): return None
            return round(float(text), 1)
        elif mode == "binary":
            if not _re.fullmatch(r"[01]+", text): return None
            return int(text, 2)
        elif mode == "roman": return _from_roman(text)
    except ValueError: return None
    return None

async def _counting_get(guild_id: int) -> dict: return await db_get_section(guild_id, "counting") or {}
async def _counting_save(guild_id: int, data: dict) -> None: await db_save_section(guild_id, "counting", data)

async def _counting_add_score(guild_id: int, user_id: int, mode: str) -> None:
    uid = str(user_id)
    lb = await db_get_section(guild_id, "counting_lb")
    lb.setdefault(uid, {})
    lb[uid]["total"] = lb[uid].get("total", 0) + 1
    lb[uid][mode] = lb[uid].get(mode, 0) + 1
    await db_save_section(guild_id, "counting_lb", lb)

async def _counting_get_lb(guild_id: int) -> dict:
    return await db_get_section(guild_id, "counting_lb")

async def _handle_counting_message(message: discord.Message) -> bool:
    if message.author.bot or not message.guild: return False
    guild_id = message.guild.id
    data = await _counting_get(guild_id)
    channels = data.get("channels", {})
    ch_id = str(message.channel.id)
    if ch_id not in channels: return False

    cfg = channels[ch_id]
    mode = cfg.get("mode", "counting")
    current = cfg.get("current", 0)
    last_user = cfg.get("last_user")

    text = message.content.strip()
    expected_str = _next_count_value(mode, current)
    parsed = _parse_count_input(mode, text)

    async def _fail(reason: str) -> None:
        try: await message.add_reaction("❌")
        except discord.HTTPException: pass
        embed = (EmbedBuilder(color=Palette.DANGER).title("❌ Wrong count!").description(f"**{message.author.display_name}** ruined it!\n\nExpected: `{expected_str}`\nYou typed: `{text}`\n\n*{reason}*\n\nThe count has been reset to **0**. Start again from `{_next_count_value(mode, 0)}`!").thumbnail(message.author.display_avatar.url).build())
        try: await message.channel.send(embed=embed)
        except discord.HTTPException: pass
        cfg["current"] = 0
        cfg["last_user"] = None
        await _counting_save(guild_id, data)

    if last_user == message.author.id:
        await _fail("You can't count twice in a row!"); return True
    if parsed is None:
        await _fail("That doesn't match this counting mode's format."); return True
    expected_val = _parse_count_input(mode, expected_str)
    if parsed != expected_val:
        await _fail(f"The next number should have been `{expected_str}`."); return True

    try: await message.add_reaction("✅")
    except discord.HTTPException: pass

    cfg["current"] = parsed
    cfg["last_user"] = message.author.id
    await _counting_save(guild_id, data)
    await _counting_add_score(guild_id, message.author.id, mode)

    milestones = {100, 500, 1000, 5000, 10000}
    numeric_val = int(parsed) if mode != "decimals" else round(parsed * 10)
    if numeric_val in milestones:
        embed = (EmbedBuilder(color=Palette.SAYORIES).title(f"🎉 Milestone reached: `{text}`!").description(f"Amazing! {message.author.mention} hit the **{text}** milestone!").build())
        try: await message.channel.send(embed=embed)
        except discord.HTTPException: pass
    return True

# ── GAMEPLAY VC SYSTEM ───────────────────────────────────────────────────────
async def _gvc_get(guild_id: int) -> dict: return await db_get_section(guild_id, "gameplay_vc") or {}
async def _gvc_save(guild_id: int, data: dict) -> None: await db_save_section(guild_id, "gameplay_vc", data)

async def _handle_gameplay_vc_cleanup(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
    if not before.channel: return
    data = await _gvc_get(member.guild.id)
    active = data.get("active_vcs", {})
    ch_id = str(before.channel.id)
    if ch_id not in active: return
    if len(before.channel.members) > 0: return
    active.pop(ch_id)
    await _gvc_save(member.guild.id, data)
    try: await before.channel.delete(reason="Gameplay session ended — VC empty")
    except (discord.HTTPException, discord.Forbidden) as e: print(f"[GameplayVC] Could not delete VC: {e}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
    await _handle_gameplay_vc_cleanup(member, before, after)

# ── SLASH COMMANDS ───────────────────────────────────────────────────────────
@tree.command(name="setsports", description="Set the channel where live soccer match updates are posted.")
@app_commands.default_permissions(administrator=True)
async def set_sports_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await db_set(interaction.guild_id, channel.id, "sports_channel")
    await interaction.response.send_message(f"✅ Live sports updates will now be sent to {channel.mention}.", ephemeral=True)

counting_group = app_commands.Group(name="counting", description="⚙️ Manage counting channels")

@counting_group.command(name="setup", description="Link a channel to a counting mode")
@app_commands.describe(mode="The counting mode to use", channel="Channel to use (defaults to current channel)")
@app_commands.choices(mode=[app_commands.Choice(name="🔢 Normal (1, 2, 3…)", value="counting"), app_commands.Choice(name="🔤 Letters (A, B, C…)", value="letter"), app_commands.Choice(name="2️⃣ ×2 (2, 4, 6…)", value="2-counting"), app_commands.Choice(name="🔣 Hexadecimal (1…9, A…F, 10…)", value="hexadecimal"), app_commands.Choice(name="5️⃣ ×5 (5, 10, 15…)", value="5-counting"), app_commands.Choice(name="💯 ×100 (100, 200…)", value="100-counting"), app_commands.Choice(name="🔟 ×10 (10, 20, 30…)", value="10-counting"), app_commands.Choice(name="🔸 Decimals (0.1, 0.2…)", value="decimals"), app_commands.Choice(name="🖥️ Binary (1, 10, 11…)", value="binary"), app_commands.Choice(name="🏛️ Roman (I, II, III…)", value="roman")])
@app_commands.checks.has_permissions(manage_channels=True)
async def counting_setup(interaction: discord.Interaction, mode: str, channel: discord.TextChannel | None = None) -> None:
    if not await guild_check(interaction):
        return
    ch = channel or interaction.channel
    guild_id = interaction.guild_id
    data = await _counting_get(guild_id)
    channels = data.setdefault("channels", {})
    channels[str(ch.id)] = {"mode": mode, "current": 0, "last_user": None}
    await _counting_save(guild_id, data)
    info = COUNTING_MODES.get(mode, {"label": mode, "emoji": "🔢"})
    first = _next_count_value(mode, 0)
    embed = (EmbedBuilder(color=Palette.SUCCESS).title(f"{info['emoji']} Counting Channel Set Up").description(f"{ch.mention} is now a **{info['label']}** counting channel!\n\nStart counting from `{first}`\n• Wrong number = reset to 0\n• You can't count twice in a row").footer("Use /counting reset to restart anytime").build())
    await interaction.response.send_message(embed=embed)

@counting_group.command(name="reset", description="Reset a counting channel back to the first value")
@app_commands.describe(channel="Channel to reset (defaults to current channel)")
@app_commands.checks.has_permissions(manage_channels=True)
async def counting_reset(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    if not await guild_check(interaction):
        return
    ch = channel or interaction.channel
    data = await _counting_get(interaction.guild_id)
    cfg = data.get("channels", {}).get(str(ch.id))
    if not cfg:
        await interaction.response.send_message(f"❌ {ch.mention} is not a counting channel yet.", ephemeral=True)
        return
    cfg["current"] = 0
    cfg["last_user"] = None
    await _counting_save(interaction.guild_id, data)
    mode = cfg.get("mode", "counting")
    info = COUNTING_MODES.get(mode, {"label": mode, "emoji": "🔢"})
    embed = (EmbedBuilder(color=Palette.SUCCESS)
        .title(f"{info['emoji']} Counting Reset")
        .description(f"{ch.mention} has been reset.\n\nNext value: `{_next_count_value(mode, 0)}`")
        .branded("Counting").build())
    await interaction.response.send_message(embed=embed)

@counting_group.command(name="info", description="Show the current state of a counting channel")
@app_commands.describe(channel="Channel to inspect (defaults to current channel)")
async def counting_info(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    if not await guild_check(interaction):
        return
    ch = channel or interaction.channel
    data = await _counting_get(interaction.guild_id)
    cfg = data.get("channels", {}).get(str(ch.id))
    if not cfg:
        await interaction.response.send_message(f"❌ {ch.mention} is not a counting channel yet.", ephemeral=True)
        return
    mode = cfg.get("mode", "counting")
    info = COUNTING_MODES.get(mode, {"label": mode, "emoji": "🔢"})
    current = cfg.get("current", 0)
    last_user = cfg.get("last_user")
    embed = (EmbedBuilder(color=Palette.INFO)
        .title(f"{info['emoji']} Counting Status")
        .fields(
            ("Channel", ch.mention),
            ("Mode", info["label"]),
            ("Current", f"`{current}`"),
            ("Next", f"`{_next_count_value(mode, current)}`"),
            ("Last Counter", f"<@{last_user}>" if last_user else "Nobody yet"),
        )
        .branded("Counting").build())
    await interaction.response.send_message(embed=embed)

@counting_group.command(name="leaderboard", description="Show the server counting leaderboard")
async def counting_leaderboard(interaction: discord.Interaction) -> None:
    if not await guild_check(interaction):
        return
    lb = await _counting_get_lb(interaction.guild_id)
    if not lb:
        await interaction.response.send_message("No counting scores yet.")
        return
    top = sorted(lb.items(), key=lambda item: item[1].get("total", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (uid, stats) in enumerate(top, 1):
        name = f"<@{uid}>"
        badge = medals[idx - 1] if idx <= 3 else f"`{idx}.`"
        lines.append(f"{badge} **{name}** • `{stats.get('total', 0):,}` correct counts")
    embed = (EmbedBuilder(color=Palette.SAYORIES)
        .title("🏆 Counting Leaderboard")
        .description("\n".join(lines))
        .branded("Counting").build())
    await interaction.response.send_message(embed=embed)

tree.add_command(counting_group)

@tree.command(name="help", description="Show all Community bot commands")
async def help_cmd(interaction: discord.Interaction) -> None:
    embed = build_help_embed("community", "Server engagement, quotes, word games, and Bocchies — this bot runs the chat.", {"⬆️ Tiers & Bocchies": ["`/rank [member]`", "`/leaderboard`", "`/tiers`", "`/bocchi_rank [member]`"], "🔢 Utilities": ["`/counting setup|reset|info|leaderboard`"]})
    await interaction.response.send_message(embed=embed)



# ─────────────────────────────  Custom Suggestions  ─────────────────────────────
CUSTOM_GUILD_ID = 1366404929727762554

# Must stay in sync with CARDS_GUILD_ID in server.py — the website only ever reads
# cards data for this single guild, so the bot must not save cards data anywhere else.
CARDS_GUILD_ID = 1366404929727762554
SUGGESTION_CHANNEL_ID = 1171457664136532010
SERVER_OWNER_ID = 879118301169602570

class SuggestionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        app_info = await bot.application_info()
        if interaction.user.id not in (app_info.owner.id, SERVER_OWNER_ID):
            await interaction.response.send_message("❌ You are not authorized to accept or reject suggestions.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="sugg_accept")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("✅ Suggestion accepted. Creating poll...", ephemeral=True)
        
        embed = interaction.message.embeds[0]
        embed.color = Palette.SUCCESS
        embed.title = "✅ Accepted Suggestion"
        await interaction.message.edit(embed=embed, view=None)

        poll_channel = interaction.guild.get_channel(1171464939437838427) or interaction.channel
        poll_msg = await poll_channel.send(content="**Suggestion Poll:** (Active for 24 hours)", embed=embed)
        await poll_msg.add_reaction("👍")
        await poll_msg.add_reaction("👎")

        author_id = None
        if embed.footer and embed.footer.text and "ID: " in embed.footer.text:
            try:
                author_id = int(embed.footer.text.split("ID: ")[-1].replace(")", "").strip())
                await db_set(interaction.guild_id, author_id, f"poll_{poll_msg.id}")
            except: pass

        async def close_poll():
            import asyncio
            await asyncio.sleep(86400)
            try:
                msg = await poll_channel.fetch_message(poll_msg.id)
                await msg.reply("This poll has concluded.")
            except:
                pass
        bot.loop.create_task(close_poll())
    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="sugg_reject")
    async def btn_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Suggestion rejected.", ephemeral=True)
        embed = interaction.message.embeds[0]
        embed.color = Palette.DANGER
        embed.title = "❌ Rejected Suggestion"
        await interaction.message.edit(embed=embed, view=None)

async def generate_card_image(card_data: dict) -> io.BytesIO:
    url = card_data.get("img", card_data.get("base_image", card_data.get("image_url", ""))).replace("&width=100", "")
    
    img = None
    if url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        img = Image.open(io.BytesIO(data)).convert("RGBA")
                    else:
                        print(f"Card image fetch failed ({resp.status}): {url}")
        except Exception as e:
            print(f"Card image fetch error for {url}: {e}")
    else:
        print(f"Card '{card_data.get('name') or card_data.get('title')}' has no image URL set")

    if not img:
        img = Image.new("RGBA", (250, 350), (40, 40, 40, 255))
        
    target_w, target_h = 250, 350
    w, h = img.size
    ratio = max(target_w / w, target_h / h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) / 2
    top = (new_h - target_h) / 2
    img = img.crop((left, top, left + target_w, top + target_h))
    
    card_type = card_data.get("type", "Unknown")
    
    # ── THEMATIC OVERLAYS ──
    # Trip & Adventure Set
    if card_type == "Texel":
        overlay = Image.new("RGBA", (target_w, target_h), (34, 139, 34, 40)) # Green/Black overlay
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(0, 0, 0), width=12)
        draw.rectangle([(2,2), (target_w-3, target_h-3)], outline=(34, 139, 34), width=8)
    elif card_type == "Berlijn":
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(0, 0, 0), width=15)
        draw.rectangle([(3,3), (target_w-4, target_h-4)], outline=(255, 0, 0), width=10)
        draw.rectangle([(6,6), (target_w-7, target_h-7)], outline=(255, 215, 0), width=5)
    elif card_type == "Tikibad":
        overlay = Image.new("RGBA", (target_w, target_h), (0, 191, 255, 60)) # Splash blue
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(32, 178, 170), width=12)
    elif card_type in ["Bobbejaanland", "Uitje"]:
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(139, 69, 19), width=14)
    # School Life Set
    elif "HAVO" in card_type or "Examen" in card_type:
        draw = ImageDraw.Draw(img)
        if card_type == "Rookie 1-2-3 HAVO":
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(173, 216, 230), width=12)
        elif card_type == "4HAVO":
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(244, 164, 96), width=12)
        elif card_type == "5HAVO":
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(255, 69, 0), width=12)
        elif card_type == "5HAVO EXAMENTIJD":
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(255, 0, 0), width=16)
            overlay = Image.new("RGBA", (target_w, target_h), (255, 0, 0, 30))
            img = Image.alpha_composite(img, overlay)
            draw = ImageDraw.Draw(img)
        elif card_type == "6HAVO":
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(50, 205, 50), width=12)
        elif card_type == "Examen Uitrijking":
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(255, 215, 0), width=20)
            draw.rectangle([(5,5), (target_w-6, target_h-6)], outline=(255, 255, 255), width=5)
    # Hangout & Gaming Set
    elif card_type == "IRL Autisten":
        draw = ImageDraw.Draw(img)
        draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(255, 250, 240), width=18)
    elif "Gamemiddagen" in card_type or "Gamemiddag" in card_type:
        draw = ImageDraw.Draw(img)
        if "Barm" in card_type:
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(138, 43, 226), width=14)
        else:
            draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=(0, 255, 0), width=14)
    else:
        draw = ImageDraw.Draw(img)
        
    rarity = card_data.get("rarity", "R")
    
    # Umamusume style rarity colors
    # SSR: Rainbow/Gold (using deep gold/orange gradient-like colors)
    # SR: Gold/Silver
    # R: Silver/Blue
    color = {"R": (192, 192, 192), "SR": (255, 215, 0), "SSR": (255, 140, 0), "USL": (255, 255, 255)}.get(rarity, (200, 200, 200))
    inner_color = {"R": (135, 206, 235), "SR": (218, 165, 32), "SSR": (255, 0, 127), "USL": (200, 200, 255)}.get(rarity, (255,255,255))
    
    # If it wasn't one of the special custom borders, draw the standard rarity border
    if card_type not in ["Texel", "Berlijn", "Tikibad", "Bobbejaanland", "Uitje", "Rookie 1-2-3 HAVO", "4HAVO", "5HAVO", "5HAVO EXAMENTIJD", "6HAVO", "Examen Uitrijking", "IRL Autisten"] and "Gamemiddag" not in card_type:
        # Outer thick border
        draw.rectangle([(0,0), (target_w-1, target_h-1)], outline=color, width=12)
        # Inner accent border to give a "metallic/framed" look
        draw.rectangle([(10,10), (target_w-11, target_h-11)], outline=inner_color, width=2)
    
    # Bottom name banner (gradient/colored instead of plain black)
    draw.rectangle([(0, target_h-55), (target_w, target_h)], fill=(20, 20, 30, 230))
    # A colored top strip for the name banner based on rarity
    draw.rectangle([(0, target_h-55), (target_w, target_h-52)], fill=color)
    
    try:
        font = load_font("bold", 18)
        font_sm = load_font("bold", 14)
    except:
        font = ImageFont.load_default()
        font_sm = ImageFont.load_default()
    
    name = card_data.get("name") or card_data.get("title", "Unknown Card")
    draw.text((15, target_h-40), name, fill=(255,255,255), font=font)
    
    card_type = card_data.get("type", "Unknown")
    type_colors = {
        "Speed": (135, 206, 235), "Stamina": (255, 165, 0),
        "Power": (255, 69, 0), "Guts": (255, 105, 180),
        "Intelligence": (50, 205, 50), "Friend": (255, 215, 0),
        "Group": (147, 112, 219),
        "Texel": (34, 139, 34), "Berlijn": (255, 0, 0),
        "Tikibad": (0, 191, 255), "Uitje": (255, 182, 193),
        "Bobbejaanland": (139, 69, 19), "IRL Autisten": (255, 250, 240)
    }
    t_col = type_colors.get(card_type, color)
    
    # Support Card Type Ribbon (Top Right)
    draw.polygon([(target_w-50, 0), (target_w, 0), (target_w, 50), (target_w-25, 40), (target_w-50, 50)], fill=t_col)
    draw.polygon([(target_w-45, 0), (target_w, 0), (target_w, 45), (target_w-25, 36), (target_w-45, 45)], outline=(255,255,255), width=2)
    
    # Type icon (first letter of type)
    short_type = card_type[0] if card_type else "?"
    if "HAVO" in card_type or "Examen" in card_type: short_type = "S" # School
    if "Gamemiddag" in card_type: short_type = "G" # Gaming
    
    draw.text((target_w-32, 8), short_type, fill=(255,255,255), font=font)
    
    # Rarity Indicator Ribbon (Top Left)
    draw.polygon([(0,0), (65,0), (55, 30), (0,30)], fill=color)
    draw.polygon([(0,0), (65,0), (55, 30), (0,30)], outline=(255,255,255), width=2)
    draw.text((10, 6), rarity, fill=(0,0,0), font=font)
    
    # Level Badge (Bottom Right above banner)
    lv = "Lv.50" if rarity == "SSR" else ("Lv.45" if rarity == "SR" else "Lv.40")
    draw.rectangle([(target_w-55, target_h-75), (target_w-5, target_h-60)], fill=(0,0,0,180), outline=color, width=1)
    draw.text((target_w-48, target_h-75), lv, fill=(255,255,255), font=font_sm)
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

@bot.tree.command(name="buy_card", description="Buy a gacha pack with Sayories")
@app_commands.choices(pack=[
    app_commands.Choice(name="Single Pull (100 Sayories)", value=1),
    app_commands.Choice(name="Mini Pack (3 Cards - 300 Sayories)", value=3),
    app_commands.Choice(name="Small Pack (5 Cards - 500 Sayories)", value=5),
    app_commands.Choice(name="Medium Pack (10 Cards - 1000 Sayories)", value=10),
    app_commands.Choice(name="Massive Pack (20 Cards - 2000 Sayories)", value=20)
])
async def buy_card(interaction: discord.Interaction, pack: app_commands.Choice[int] = None):
    guild_id = interaction.guild_id
    if not guild_id:
        return await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
        
    if guild_id != CARDS_GUILD_ID:
        return await interaction.response.send_message("❌ Trading cards are not available in this server.", ephemeral=True)
        
    count = pack.value if pack else 1
    cost = 100 * count
    
    # Check balance using shared global logic to ensure parity with dashboard
    import shared
    bal = await shared.g_eco_get(interaction.user.id)
    if bal < cost:
        embed = EmbedBuilder(color=Palette.DANGER).title("Not enough Sayories!").description(f"You need {cost} Sayories for this pack. You only have {bal}.").build()
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    templates = await shared.cards_get_templates(guild_id)
    if not templates:
        await interaction.response.send_message("No cards exist in this server yet!", ephemeral=True)
        return
        
    rarities = await shared.cards_get_rarities(guild_id)
    if isinstance(rarities, dict): rarities = rarities.get("rarities", [])
    if not rarities:
        rarities = [
            {'name': 'C', 'chance': 45.0}, {'name': 'UC', 'chance': 30.0},
            {'name': 'R', 'chance': 15.0}, {'name': 'SR', 'chance': 6.0},
            {'name': 'SSR', 'chance': 3.0}, {'name': 'SSL', 'chance': 0.9},
            {'name': 'USL', 'chance': 0.1}
        ]
        
    from collections import defaultdict
    import random, time, uuid
    cards_by_rarity = defaultdict(list)
    for c in templates:
        cards_by_rarity[c.get('rarity', 'C')].append(c)

    await interaction.response.defer()
    
    # deduct balance
    await shared.g_eco_add(interaction.user.id, -cost)
    
    pulled_templates = []
    pulled_items = []
    
    for _ in range(count):
        rand_val = random.uniform(0, 100)
        cumulative = 0.0
        selected_rarity = None
        for r in rarities:
            r_chance = float(r.get('chance', 0))
            if r_chance <= 0: continue
            cumulative += r_chance
            if rand_val <= cumulative:
                selected_rarity = r.get('name')
                break
                
        if not selected_rarity or not cards_by_rarity.get(selected_rarity):
            card = random.choice(templates)
        else:
            card = random.choice(cards_by_rarity[selected_rarity])
            
        pulled_templates.append(card)
        pulled_items.append({'id': str(uuid.uuid4()), 'template_id': card.get('id', str(uuid.uuid4())), 'timestamp': int(time.time()), 'locked': False})
        
    # Save to DB
    inv = await shared.cards_get_inventory(guild_id, interaction.user.id)
    cards_list = inv.get('cards', [])
    cards_list.extend(pulled_items)
    inv['cards'] = cards_list
    await shared.cards_save_inventory(guild_id, interaction.user.id, inv)

    # Generate Image
    if count == 1:
        buf = await generate_card_image(pulled_templates[0])
        file = discord.File(fp=buf, filename="card.png")
        embed = EmbedBuilder(color=Palette.PRIMARY).title(f"🎉 Pulled: {pulled_templates[0].get('title') or pulled_templates[0].get('name', 'Unknown')}!").build()
        embed.set_image(url="attachment://card.png")
        await interaction.followup.send(embed=embed, file=file)
    else:
        # Create a grid for multiple cards
        import math
        from PIL import Image
        
        cols = 5 if count >= 5 else count
        rows = math.ceil(count / cols)
        
        card_w, card_h = 300, 420
        grid_w = cols * card_w + (cols - 1) * 10
        grid_h = rows * card_h + (rows - 1) * 10
        
        grid_img = Image.new('RGB', (grid_w, grid_h), (20, 20, 20))
        
        import io
        for idx, t in enumerate(pulled_templates):
            c_buf = await generate_card_image(t)
            c_img = Image.open(c_buf)
            
            x = (idx % cols) * (card_w + 10)
            y = (idx // cols) * (card_h + 10)
            grid_img.paste(c_img, (x, y))
            
        out_buf = io.BytesIO()
        grid_img.save(out_buf, format="PNG")
        out_buf.seek(0)
        
        file = discord.File(fp=out_buf, filename="pack.png")
        embed = EmbedBuilder(color=Palette.PRIMARY).title(f"🎉 You opened a {count}-Card Pack!").build()
        embed.set_image(url="attachment://pack.png")
        await interaction.followup.send(embed=embed, file=file)

@bot.tree.command(name="inventory", description="View your card collection")
async def inventory(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if not guild_id:
        await interaction.response.send_message("Must be used in a server.", ephemeral=True)
        return
        
    if guild_id != CARDS_GUILD_ID:
        return await interaction.response.send_message("❌ Trading cards are not available in this server.", ephemeral=True)

    user_inv = await shared.cards_get_inventory(guild_id, interaction.user.id)
    cards_list = user_inv.get('cards', [])
    
    if not cards_list:
        await interaction.response.send_message("Your inventory is empty.", ephemeral=True)
        return
        
    counts = {}
    for c in cards_list:
        tid = c.get('template_id')
        if tid:
            counts[tid] = counts.get(tid, 0) + 1
            
    templates = await shared.cards_get_templates(guild_id)
    
    lines = []
    for tid, count in counts.items():
        card = next((t for t in templates if str(t.get("id")) == str(tid)), None)
        if card:
            lines.append(f"**{card.get('name', 'Unknown')}** ({card.get('rarity', 'C')}) x{count}")
            
    if not lines:
        await interaction.response.send_message("Your inventory is empty.", ephemeral=True)
        return
        
    pages = []
    chunk = []
    for line in lines:
        chunk.append(line)
        if len(chunk) == 10:
            pages.append("\n".join(chunk))
            chunk = []
    if chunk:
        pages.append("\n".join(chunk))
        
    embed = EmbedBuilder(color=Palette.INFO).title("Your Card Collection").description(pages[0]).footer(f"Page 1 of {len(pages)}").build()
    await interaction.response.send_message(embed=embed)
@tasks.loop(seconds=10)
async def check_web_suggestions():
    import json
    import os
    from pathlib import Path
    
    # Try MongoDB first
    from shared import _get_mongo_db
    db = _get_mongo_db()
    processing = []
    
    if db is not None:
        cursor = db.web_suggestions.find().limit(5)
        docs = await cursor.to_list(length=5)
        for doc in docs:
            processing.append(doc)
            await db.web_suggestions.delete_one({"_id": doc["_id"]})
    else:
        WEB_SUGG_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / "data" / "web_suggestions.json"
        if WEB_SUGG_FILE.exists():
            try:
                with open(WEB_SUGG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                queue = data.get("queue", [])
                if not queue: return
                
                processing = queue[:5]
                data["queue"] = queue[5:]
                with open(WEB_SUGG_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            except: return
            
    if not processing: return
    
    guild = bot.get_guild(CUSTOM_GUILD_ID)
    if not guild: return
    sugg_channel = guild.get_channel(SUGGESTION_CHANNEL_ID)
    if not sugg_channel: return
    
    for item in processing:
        user_id = item.get("user_id")
        suggestion = item.get("suggestion")
        if not user_id or not suggestion: continue
        
        member = guild.get_member(int(user_id))
        if not member:
            try:
                member = await guild.fetch_member(int(user_id))
            except:
                continue
                
        embed = (EmbedBuilder(color=Palette.INFO)
                 .title("💡 New Suggestion (Web)")
                 .description(suggestion)
                 .footer(f"Suggested by {member} (ID: {member.id})")
                 .build())
                 
        view = SuggestionView()
        await sugg_channel.send(embed=embed, view=view)

if __name__ == "__main__":
    TOKEN = os.getenv("COMMUNITY_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the COMMUNITY_BOT_TOKEN environment variable.")
    bot.run(TOKEN)