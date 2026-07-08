from __future__ import annotations
import os
import random

import discord
from discord import app_commands
from discord.ext import commands

from shared import *
from theme import EmbedBuilder, Palette
from ui_kit import install_error_handler

SUITS  = ["♠️","♥️","♦️","♣️"]
VALUES = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]

def make_deck() -> list[str]: return [f"{v}{s}" for s in SUITS for v in VALUES]
def card_value(card: str) -> int:
    v = card[:-2] if len(card) > 3 else card[0]
    if v in "JQK": return 10
    if v == "A": return 11
    return int(v)
def hand_value(hand: list[str]) -> int:
    total = sum(card_value(c) for c in hand)
    aces  = sum(1 for c in hand if c.startswith("A"))
    while total > 21 and aces: total -= 10; aces -= 1
    return total

class GamblingBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="§unused-gambling§", intents=intents, help_command=None)
        self._bj: dict = {}
        self._uno: dict = {}
        self._roulette: dict = {}

    async def on_ready(self):
        print("🔄 Syncing gambling bot commands…")
        asyncio.create_task(safe_sync(self))
        print_banner("gambling", self)
        await self.change_presence(activity=discord.CustomActivity(name=BOT_INFO["gambling"]["status"]))

bot = GamblingBot()
tree = bot.tree
install_error_handler(tree)

def _bj_embed(player, dealer, bet, reveal_dealer=False, title="🃏 Blackjack Table", result_text="", color=Palette.SUCCESS):
    builder = EmbedBuilder(color=color).title(title)
    builder.field(f"🎴 Your Hand `{hand_value(player)}`", " ".join(player))
    if reveal_dealer: builder.field(f"🂠 Dealer Hand `{hand_value(dealer)}`", " ".join(dealer))
    else: builder.field("🂠 Dealer Hand", f"{dealer[0]}  🂠")
    builder.field("💰 Bet", f"{bet:,} Sayories", inline=False)
    if result_text: builder.field("📊 Result", result_text, inline=False)
    return builder.build()

class BlackjackView(discord.ui.View):
    def __init__(self, user, player, dealer, deck, bet):
        super().__init__(timeout=120)
        self.user, self.player, self.dealer, self.deck, self.bet = user, player, dealer, deck, bet
        self.done = False
        self.double_btn.disabled = len(player) != 2

    def _disable_all(self) -> None:
        for item in self.children:
            item.disabled = True

    async def _finish(self, interaction: discord.Interaction, reason: str):
        self.done = True
        self.stop()
        self._disable_all()
        pval = hand_value(self.player)

        if reason == "bust":
            result = f"💥 **Bust!** Over 21 — you lose **{self.bet:,} Sayories**."
            color = Palette.DANGER
        else:
            while hand_value(self.dealer) < 17: self.dealer.append(self.deck.pop())
            dval = hand_value(self.dealer)
            if reason == "blackjack":
                payout = int(self.bet * 2.5)
                await g_eco_add(self.user.id, payout)
                result = f"🃏 **BLACKJACK!** You receive **{payout:,} Sayories**! (×2.5)"
                color = Palette.SAYORIES
            elif dval > 21 or pval > dval:
                await g_eco_add(self.user.id, self.bet * 2)
                result = f"✅ **You win!** You beat the dealer and receive **{self.bet * 2:,} Sayories**!"; color = Palette.SUCCESS
            elif pval == dval:
                await g_eco_add(self.user.id, self.bet)
                result = "🤝 **Push!** It's a tie — your bet is returned."; color = Palette.INFO
            else:
                result = f"❌ **Dealer wins.** You lose **{self.bet:,} Sayories**."; color = Palette.DANGER

        embed = _bj_embed(self.player, self.dealer, self.bet, reveal_dealer=True, title="🃏 Blackjack — Final Result", result_text=result, color=color)
        embed.set_footer(text=f"Bet: {self.bet:,} 🪙 • Barm assistant Blackjack")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎴 Hit", style=discord.ButtonStyle.primary)
    async def hit_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user.id: return await interaction.response.send_message("This isn't your game!", ephemeral=True)
        if self.done: return
        self.double_btn.disabled = True
        self.player.append(self.deck.pop())
        pval = hand_value(self.player)
        if pval > 21: await self._finish(interaction, "bust"); return
        if pval == 21: await self._finish(interaction, "stand"); return
        embed = _bj_embed(self.player, self.dealer, self.bet, title="🃏 Blackjack — Hit!")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🛑 Stand", style=discord.ButtonStyle.danger)
    async def stand_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user.id: return await interaction.response.send_message("This isn't your game!", ephemeral=True)
        if self.done: return
        await self._finish(interaction, "stand")

    @discord.ui.button(label="Double", emoji="⬆️", style=discord.ButtonStyle.success)
    async def double_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("This isn't your game!", ephemeral=True)
        if self.done:
            return
        if len(self.player) != 2:
            return await interaction.response.send_message("You can only double down on your first move.", ephemeral=True)
        bal = await g_eco_get(self.user.id)
        if bal < self.bet:
            return await interaction.response.send_message(f"❌ You need another **{self.bet:,} Sayories** to double down.", ephemeral=True)
        await g_eco_add(self.user.id, -self.bet)
        self.bet *= 2
        self.player.append(self.deck.pop())
        await self._finish(interaction, "bust" if hand_value(self.player) > 21 else "stand")

_ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

def _roulette_color(number: int) -> str:
    if number == 0:
        return "green"
    return "red" if number in _ROULETTE_RED else "black"

def _roulette_embed(user: discord.User | discord.Member, bet: int, *, title: str = "🎡 Roulette Table", result: str = "", color: int = Palette.PRIMARY) -> discord.Embed:
    builder = (EmbedBuilder(color=color)
        .title(title)
        .description(f"**{user.display_name}**, choose a colour to spin the wheel.")
        .fields(
            ("Bet", f"`{bet:,}` Sayories"),
            ("Payouts", "🔴 Red `2x` • ⚫ Black `2x` • 🟢 Green `14x`"),
            inline=False,
        )
        .branded("Roulette"))
    if result:
        builder.field("Result", result, inline=False)
    return builder.build()

class RouletteView(discord.ui.View):
    def __init__(self, user: discord.User | discord.Member, bet: int):
        super().__init__(timeout=60)
        self.user = user
        self.bet = bet
        self.done = False
        self.message: discord.Message | None = None

    def _disable_all(self) -> None:
        for item in self.children:
            item.disabled = True

    async def _spin(self, interaction: discord.Interaction, choice: str) -> None:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This roulette table isn't yours.", ephemeral=True)
            return
        if self.done:
            return

        self.done = True
        self.stop()
        self._disable_all()

        number = random.randint(0, 36)
        result_color = _roulette_color(number)
        won = result_color == choice
        multiplier = 14 if choice == "green" else 2
        payout = self.bet * multiplier if won else 0
        if won:
            new_bal = await g_eco_add(self.user.id, payout)
            result = f"**{number} {result_color.upper()}** — you won **{payout:,} Sayories**!\nNew balance: **{new_bal:,} Sayories**"
            embed_color = Palette.SUCCESS if choice != "green" else Palette.SAYORIES
        else:
            new_bal = await g_eco_get(self.user.id)
            result = f"**{number} {result_color.upper()}** — no hit this time.\nLost: **{self.bet:,} Sayories** • Balance: **{new_bal:,} Sayories**"
            embed_color = Palette.DANGER

        embed = _roulette_embed(self.user, self.bet, title="🎡 Roulette — Final Result", result=result, color=embed_color)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        if self.done:
            return
        self.done = True
        self._disable_all()
        await g_eco_add(self.user.id, self.bet)
        if self.message:
            embed = _roulette_embed(self.user, self.bet, title="🎡 Roulette Expired", result="No colour was picked in time, so the bet was refunded.", color=Palette.WARNING)
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Red", emoji="🔴", style=discord.ButtonStyle.danger)
    async def red_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._spin(interaction, "red")

    @discord.ui.button(label="Black", emoji="⚫", style=discord.ButtonStyle.secondary)
    async def black_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._spin(interaction, "black")

    @discord.ui.button(label="Green", emoji="🟢", style=discord.ButtonStyle.success)
    async def green_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._spin(interaction, "green")

@tree.command(name="blackjack", description="🃏 Play Blackjack with buttons — Hit, Stand or Double Down!")
@app_commands.describe(bet="How many Sayories to bet")
async def blackjack(interaction: discord.Interaction, bet: int):
    if not await dm_check(interaction): return
    if bet <= 0: return await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True)
    bal = await g_eco_get(interaction.user.id)
    if bal < bet: return await interaction.response.send_message(f"❌ Not enough Sayories (you have {bal:,}).", ephemeral=True)
    if interaction.user.id in bot._bj: return await interaction.response.send_message("❌ You already have an active game — finish it first!", ephemeral=True)

    deck = make_deck(); random.shuffle(deck)
    player = [deck.pop(), deck.pop()]; dealer = [deck.pop(), deck.pop()]
    bot._bj[interaction.user.id] = True
    await g_eco_add(interaction.user.id, -bet)

    pval = hand_value(player)
    view = BlackjackView(interaction.user, player, dealer, deck, bet)

    if pval == 21:
        bot._bj.pop(interaction.user.id, None)
        payout = int(bet * 2.5); await g_eco_add(interaction.user.id, payout)
        result = f"🃏 **BLACKJACK!** You receive **{payout:,} Sayories**! (×2.5)"
        embed = _bj_embed(player, dealer, bet, reveal_dealer=True, title="🃏 Blackjack — BLACKJACK!", result_text=result, color=Palette.SAYORIES)
        embed.set_footer(text=f"Bet: {bet:,} 🪙 • Barm assistant Blackjack")
        return await interaction.response.send_message(embed=embed)

    embed = _bj_embed(player, dealer, bet, title="🃏 Blackjack Table", color=Palette.SUCCESS)
    embed.set_footer(text="🎴 Hit  •  🛑 Stand  •  ⬆️ Double Down (first 2 cards only)")
    await interaction.response.send_message(embed=embed, view=view)
    await view.wait()
    bot._bj.pop(interaction.user.id, None)

@tree.command(name="slots", description="🎰 Play the Fruit Machine!")
@app_commands.describe(bet="Amount of Sayories to bet")
async def slots(interaction: discord.Interaction, bet: int):
    if not await dm_check(interaction): return
    if bet <= 0: return await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True)
    bal = await g_eco_get(interaction.user.id)
    if bal < bet: return await interaction.response.send_message(f"❌ Not enough Sayories (you have {bal:,}).", ephemeral=True)
    await g_eco_add(interaction.user.id, -bet)

    SLOT_SYMBOLS = ["🍒","🍋","🍊","🍇","🔔","💎","7️⃣"]
    SLOT_WEIGHTS = [28, 24, 20, 16, 8,  4,  2]
    SLOT_MULTS   = {"💎":50,"7️⃣":30,"🔔":15,"🍇":10,"🍊":7,"🍋":5,"🍒":3}
    reels = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
    display = f"[ {reels[0]}  {reels[1]}  {reels[2]} ]"

    if reels[0] == reels[1] == reels[2]:
        m = SLOT_MULTS.get(reels[0], 3); payout = bet * m
        new_bal = await g_eco_add(interaction.user.id, payout); net = payout - bet
        embed = (EmbedBuilder(color=Palette.SAYORIES).title("🎰 FRUIT MACHINE — JACKPOT!!!").description(f"```\n╔══════════════════╗\n║  {display}  ║\n╚══════════════════╝```\n### 🎉 THREE {reels[0]} — JACKPOT! (×{m})\nYou win **+{net:,} Sayories**!").fields(("💰 Payout", f"{payout:,} Sayories"), ("🏦 Balance", f"{new_bal:,} Sayories")).build())
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        p = int(bet * 2); new_bal = await g_eco_add(interaction.user.id, p)
        embed = (EmbedBuilder(color=Palette.SUCCESS).title("🎰 Fruit Machine — Two of a Kind!").description(f"```\n╔══════════════════╗\n║  {display}  ║\n╚══════════════════╝```\n✨ Two matching symbols! You win **+{p - bet:,} Sayories**! (×2)").fields(("💰 Payout", f"{p:,} Sayories"), ("🏦 Balance", f"{new_bal:,} Sayories")).build())
    else:
        new_bal = await g_eco_get(interaction.user.id)
        embed = (EmbedBuilder(color=Palette.DANGER).title("🎰 Fruit Machine — No Match").description(f"```\n╔══════════════════╗\n║  {display}  ║\n╚══════════════════╝```\n❌ No matching symbols. You lose **{bet:,} Sayories**.").fields(("💸 Lost", f"{bet:,} Sayories"), ("🏦 Balance", f"{new_bal:,} Sayories")).build())
    embed.set_footer(text=f"Bet: {bet:,} 🪙 • 💎×50 | 7️⃣×30 | 🔔×15 | 🍇×10 | 🍊×7 | 🍋×5 | 🍒×3")
    await interaction.response.send_message(embed=embed)

@tree.command(name="roulette", description="🎡 Bet Sayories on red, black, or green")
@app_commands.describe(bet="Amount of Sayories to bet")
async def roulette(interaction: discord.Interaction, bet: int):
    if not await dm_check(interaction): return
    if bet <= 0: return await interaction.response.send_message("❌ Bet must be positive.", ephemeral=True)
    bal = await g_eco_get(interaction.user.id)
    if bal < bet: return await interaction.response.send_message(f"❌ Not enough Sayories (you have {bal:,}).", ephemeral=True)
    if interaction.user.id in bot._roulette: return await interaction.response.send_message("❌ You already have an active roulette table.", ephemeral=True)

    bot._roulette[interaction.user.id] = True
    await g_eco_add(interaction.user.id, -bet)
    view = RouletteView(interaction.user, bet)
    embed = _roulette_embed(interaction.user, bet)
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()
    await view.wait()
    bot._roulette.pop(interaction.user.id, None)

@tree.command(name="help", description="Show all Gambling bot commands")
async def help_cmd(interaction: discord.Interaction):
    embed = build_help_embed("gambling", "Casino games — all bets are paid from your global Sayories balance.", {"🃏 Blackjack": ["`/blackjack <bet>` — Hit, Stand, or Double Down with buttons"], "🎰 Roulette & Slots": ["`/roulette <bet>` — pick a colour with buttons", "`/slots <bet>` — play the Fruit Machine"]})
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("GAMBLING_BOT_TOKEN")
    if not TOKEN: raise SystemExit("Set the GAMBLING_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
