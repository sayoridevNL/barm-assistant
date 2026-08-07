import discord
from discord.ext import commands, tasks
import requests
import asyncio
import time
from datetime import datetime
from shared import db_get, db_set, add_bal

# --- CONFIGURATION ---
TARGET_GUILD_ID = 1049396166250475612
WHITELISTED_IDS = [1158703899843231836, 899372657554894909, 907956482207776778, 315845909533556741, 787681263267479572, 1513484108033163309, 879118301169602570, 748110757400674324, 431864554910121994]
TARGET_USER_ID = 879118301169602570
LEAGUES = ['ned.1', 'ned.2', 'ned.cup']
API_URL = "http://site.api.espn.com/apis/site/v2/sports/soccer/{}/scoreboard"

COLOR_GOAL = 0x2ecc71
COLOR_YELLOW = 0xf1c40f
COLOR_RED = 0xe74c3c
COLOR_MATCH = 0x3498db

class SportsTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.seen_events = set()
        self.match_tracker.start()
        self.toto_daily.start()
        
    def cog_unload(self):
        self.match_tracker.cancel()
        self.toto_daily.cancel()

    def get_channel(self):
        guild = self.bot.get_guild(TARGET_GUILD_ID)
        if not guild: return None
        for ch in guild.text_channels:
            if "sport" in ch.name.lower() or "voetbal" in ch.name.lower():
                return ch
        return guild.system_channel or guild.text_channels[0]

    def fetch_league_matches(self, league, date_str=None):
        url = API_URL.format(league)
        if date_str: url += f"?dates={date_str}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.json().get('events', [])
        except: pass
        return []

    def extract_new_events(self, match):
        new_events = []
        try:
            competition = match['competitions'][0]
            details = competition.get('details', [])
            for det in details:
                evt_id = det.get('id')
                if not evt_id or evt_id in self.seen_events: continue
                
                type_text = det.get('type', {}).get('text', '')
                clock = det.get('clock', {}).get('displayValue', '')
                team_id = det.get('team', {}).get('id')
                
                team_name = "Unknown Team"
                for comp in competition.get('competitors', []):
                    if comp['team']['id'] == team_id:
                        team_name = comp['team']['displayName']
                        break
                
                players = [ath.get('displayName', 'Unknown') for ath in det.get('athletesInvolved', [])]
                player_str = ", ".join(players) if players else "Unknown Player"
                
                new_events.append({
                    'id': evt_id, 'type': type_text, 'time': clock,
                    'team': team_name, 'player': player_str, 'match_name': match['name']
                })
                self.seen_events.add(evt_id)
        except: pass
        return new_events

    @tasks.loop(seconds=30)
    async def match_tracker(self):
        channel = self.get_channel()
        if not channel: return
        
        today_str = datetime.now().strftime("%Y%m%d")
        toto_key = f"toto_battle_{today_str}"
        battle = await db_get("global", toto_key)
        
        all_matches = []
        
        for league in LEAGUES:
            matches = self.fetch_league_matches(league)
            all_matches.extend(matches)
            for match in matches:
                state = match.get('status', {}).get('type', {}).get('state', '')
                if state == 'in':
                    new_events = self.extract_new_events(match)
                    for ev in new_events:
                        embed = discord.Embed(title=f"⚽ {ev['match_name']}", description=f"**{ev['time']}** - {ev['team']}", color=COLOR_MATCH)
                        if 'Goal' in ev['type']:
                            embed.color = COLOR_GOAL
                            embed.add_field(name="🚨 GOAL! 🚨", value=f"**{ev['player']}** has scored!", inline=False)
                        elif 'Yellow' in ev['type']:
                            embed.color = COLOR_YELLOW
                            embed.add_field(name="🟨 Yellow Card", value=f"**{ev['player']}** received a yellow card.", inline=False)
                        elif 'Red' in ev['type']:
                            embed.color = COLOR_RED
                            embed.add_field(name="🟥 Red Card", value=f"**{ev['player']}** received a red card!", inline=False)
                        else:
                            embed.add_field(name=ev['type'], value=ev['player'], inline=False)
                            
                        try:
                            comp = match['competitions'][0]['competitors']
                            score_str = f"{comp[0]['team']['abbreviation']} {comp[0]['score']} - {comp[1]['score']} {comp[1]['team']['abbreviation']}"
                            embed.set_footer(text=f"Current Score: {score_str}")
                        except: pass
                        
                        await channel.send(embed=embed)
                        
                # State changes (halftime / fulltime)
                match_id = match['id']
                state_key = f"match_state_{match_id}"
                last_state = await db_get("global", state_key)
                
                desc = match.get('status', {}).get('type', {}).get('description', '')
                current_stage = desc
                
                if last_state != current_stage:
                    if current_stage in ['Halftime', 'Full Time', 'Final']:
                        try:
                            comp = match['competitions'][0]['competitors']
                            score_str = f"{comp[0]['team']['name']} {comp[0]['score']} - {comp[1]['score']} {comp[1]['team']['name']}"
                            embed = discord.Embed(title=f"⏱️ {current_stage}: {match['name']}", description=f"**Score:** {score_str}", color=COLOR_MATCH)
                            await channel.send(embed=embed)
                        except: pass
                    await db_set("global", current_stage, state_key)

        # Check Toto Battle Resolution
        if battle and not battle.get("resolved"):
            all_completed = True
            for mid in battle["matches"]:
                m = next((m for m in all_matches if m['id'] == mid), None)
                if m:
                    state = m.get('status', {}).get('type', {}).get('state', '')
                    if state != 'post':
                        all_completed = False
                        break
                else:
                    pass
            
            if all_completed and len(all_matches) > 0:
                await self.resolve_battle(battle, all_matches, toto_key)

    async def resolve_battle(self, battle, all_matches, toto_key):
        p1 = str(battle['p1'])
        p2 = str(battle['p2'])
        p1_picks = battle.get("picks", {}).get(p1, {})
        p2_picks = battle.get("picks", {}).get(p2, {})
        
        p1_score = 0
        p2_score = 0
        
        for match in all_matches:
            if match['id'] not in battle['matches']: continue
            comp = match['competitions'][0]['competitors']
            home = next(c for c in comp if c['homeAway'] == 'home')
            away = next(c for c in comp if c['homeAway'] == 'away')
            h_score = int(home.get('score', 0))
            a_score = int(away.get('score', 0))
            
            if h_score > a_score: actual = "1"
            elif h_score < a_score: actual = "2"
            else: actual = "X"
            
            if p1_picks.get(match['id']) == actual: p1_score += 1
            if p2_picks.get(match['id']) == actual: p2_score += 1
            
        battle["resolved"] = True
        await db_set("global", battle, toto_key)
        
        guild = self.bot.get_guild(TARGET_GUILD_ID)
        if not guild: return
        u1 = guild.get_member(int(p1))
        u2 = guild.get_member(int(p2))
        
        if p1_score > p2_score:
            w, l = u1, u2
            await add_bal(int(p1), 25000)
            await add_bal(int(p2), 500)
        elif p2_score > p1_score:
            w, l = u2, u1
            await add_bal(int(p2), 25000)
            await add_bal(int(p1), 500)
        else:
            w, l = None, None
            await add_bal(int(p1), 500)
            await add_bal(int(p2), 500)
            
        msg = f"⚽ **Toto Battle Resolved!** ⚽\n\n<@{p1}> Score: {p1_score}\n<@{p2}> Score: {p2_score}\n\n"
        if w: msg += f"🏆 **<@{w.id}> WINS 25,000 Sayories!**\n<@{l.id}> receives 500 Sayories for participating."
        else: msg += "🤝 **It's a TIE!** Both players receive 500 Sayories."
        
        for u in [u1, u2]:
            if u:
                try: await u.send(msg)
                except: pass

    @tasks.loop(minutes=60)
    async def toto_daily(self):
        import random
        hour = datetime.now().hour
        if hour < 7 or hour > 10: return
        
        today_str = datetime.now().strftime("%Y%m%d")
        toto_key = f"toto_battle_{today_str}"
        
        has_run = await db_get("global", toto_key)
        if has_run: return
        
        all_matches = []
        for league in LEAGUES:
            matches = self.fetch_league_matches(league, date_str=today_str)
            all_matches.extend(matches)
            
        if not all_matches: return
        
        opponents = [u for u in WHITELISTED_IDS if u != TARGET_USER_ID]
        chosen_opp = random.choice(opponents)
        
        match_data = []
        for m in all_matches:
            comp = m['competitions'][0]['competitors']
            home = next((c for c in comp if c['homeAway'] == 'home'), comp[0])
            away = next((c for c in comp if c['homeAway'] == 'away'), comp[1])
            match_data.append({
                "id": m['id'],
                "name": f"{home['team']['name']} vs {away['team']['name']}"
            })
        
        await db_set("global", {
            "p1": TARGET_USER_ID,
            "p2": chosen_opp,
            "matches": [m['id'] for m in all_matches],
            "match_data": match_data,
            "picks": {},
            "resolved": False
        }, toto_key)
        
        guild = self.bot.get_guild(TARGET_GUILD_ID)
        if guild:
            u1 = guild.get_member(TARGET_USER_ID)
            u2 = guild.get_member(chosen_opp)
            msg = f"⚽ **Toto Prediction Battle!** ⚽\nYou have been challenged for today's matches!\n\nOpponent: <@{chosen_opp if u1 else TARGET_USER_ID}>\nMatches today: {len(all_matches)}\n\nGo to the **Web Dashboard** and check the **Prediction Battle** tab to lock in your predictions!\nPrize: **25,000 Sayories**"
            
            if u1: 
                try: await u1.send(msg)
                except: pass
            if u2:
                try: await u2.send(msg.replace(f"<@{chosen_opp}>", f"<@{TARGET_USER_ID}>"))
                except: pass

    @match_tracker.before_loop
    async def before_match_tracker(self):
        await self.bot.wait_until_ready()
        
    @toto_daily.before_loop
    async def before_toto_daily(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(SportsTracker(bot))
