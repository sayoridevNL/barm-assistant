import discord
from discord.ext import commands, tasks
import requests
import asyncio
import traceback
from shared import global_get_section, global_save_section

# --- CONFIGURATION ---
SPORTS_CHANNEL_ID = 1535258343675789322
LEAGUES = ['ned.1', 'ned.2', 'ned.cup']
API_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{}/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{}/summary?event={}"

COLOR_GOAL = 0x2ecc71
COLOR_YELLOW = 0xf1c40f
COLOR_RED = 0xe74c3c
COLOR_MATCH = 0x3498db

class SportsTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.seen_events = set()
        self.match_tracker.start()

    def cog_unload(self):
        self.match_tracker.cancel()

    async def get_channel(self):
        channel = self.bot.get_channel(SPORTS_CHANNEL_ID)
        if channel:
            return channel
        try:
            return await self.bot.fetch_channel(SPORTS_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            print(f"[Sports] Could not access sports channel {SPORTS_CHANNEL_ID}: {exc}")
            return None

    async def fetch_league_matches(self, league, date_str=None):
        url = API_URL.format(league)
        if date_str: url += f"?dates={date_str}"
        try:
            r = await asyncio.to_thread(requests.get, url, timeout=10)
            if r.status_code == 200:
                return r.json().get('events', [])
        except requests.RequestException as exc:
            print(f"[Sports] Could not fetch {league}: {exc}")
        return []

    async def fetch_match_details(self, league, match_id):
        """The scoreboard omits play-by-play details; the summary endpoint has them."""
        try:
            response = await asyncio.to_thread(
                requests.get, SUMMARY_URL.format(league, match_id), timeout=10
            )
            if response.status_code != 200:
                return []
            payload = response.json()
            header = payload.get("header", {})
            competitions = header.get("competitions", [])
            # Depending on the ESPN feed, live events appear either on the
            # competition or in the top-level commentary collection.
            details = competitions[0].get("details", []) if competitions else []
            return details or payload.get("commentary", [])
        except requests.RequestException as exc:
            print(f"[Sports] Could not fetch match {match_id}: {exc}")
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
        except Exception as exc:
            print(f"[Sports] Error extracting events: {exc}")
        return new_events

    @tasks.loop(seconds=30)
    async def match_tracker(self):
        # Wrapped in try/except: an unhandled exception here would silently
        # kill this whole loop forever (discord.py's tasks.loop does not
        # auto-restart on error), taking down all live updates with it.
        try:
            channel = await self.get_channel()
            if not channel:
                return

            for league in LEAGUES:
                matches = await self.fetch_league_matches(league)
                for match in matches:
                    try:
                        await self.process_match(league, match, channel)
                    except Exception as exc:
                        print(f"[Sports] Error processing match {match.get('id')}: {exc}")
                        traceback.print_exc()
        except Exception as exc:
            print(f"[Sports] FATAL ERROR IN match_tracker: {exc}")
            traceback.print_exc()

    async def process_match(self, league, match, channel):
        """Handle live-event embeds and halftime/full-time updates for a single match."""
        state = match.get('status', {}).get('type', {}).get('state', '')
        if state == 'in':
            competition = match.get('competitions', [{}])[0]
            # ESPN's scoreboard payload has an empty `details` list. Fill it
            # from the match summary before looking for goals and cards.
            if not competition.get('details'):
                competition['details'] = await self.fetch_match_details(league, match['id'])
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
                except Exception:
                    pass

                await channel.send(embed=embed)

        # State changes (halftime / fulltime)
        match_id = match['id']
        state_key = f"match_state_{match_id}"

        state_doc = await global_get_section(state_key)
        last_state = (state_doc or {}).get("state", "")

        desc = match.get('status', {}).get('type', {}).get('description', '')
        current_stage = desc

        if last_state != current_stage:
            if current_stage in ['Halftime', 'Full Time', 'Final']:
                try:
                    comp = match['competitions'][0]['competitors']
                    score_str = f"{comp[0]['team']['name']} {comp[0]['score']} - {comp[1]['score']} {comp[1]['team']['name']}"
                    embed = discord.Embed(title=f"⏱️ {current_stage}: {match['name']}", description=f"**Score:** {score_str}", color=COLOR_MATCH)
                    await channel.send(embed=embed)
                except Exception:
                    pass
            await global_save_section(state_key, {"state": current_stage})

    @match_tracker.before_loop
    async def before_match_tracker(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(SportsTracker(bot))