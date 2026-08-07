import asyncio
from datetime import datetime
from shared import global_get_section, global_save_section

LEAGUES = ['ned.1', 'ned.2', 'ned.cup']
TARGET_USER_ID = 879118301169602570
WHITELISTED_IDS = [1158703899843231836, 899372657554894909, 907956482207776778, 315845909533556741, 787681263267479572, 1513484108033163309, 879118301169602570, 748110757400674324, 431864554910121994]

async def test_toto():
    import random
    import requests
    today_str = datetime.now().strftime('%Y%m%d')
    toto_key = f'toto_battle_{today_str}'
    
    print('Checking has_run...')
    has_run = await global_get_section(toto_key)
    print('has_run =', has_run)
    if has_run:
        print('Already run!')
        return
        
    print('Fetching matches...')
    all_matches = []
    for league in LEAGUES:
        url = f'http://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={today_str}'
        r = requests.get(url)
        data = r.json()
        matches = data.get('events', [])
        all_matches.extend(matches)
        
    print(f'Found {len(all_matches)} matches')
    if not all_matches: return
    
    opponents = [u for u in WHITELISTED_IDS if u != TARGET_USER_ID]
    chosen_opp = random.choice(opponents)
    
    match_data = []
    for m in all_matches:
        comp = m['competitions'][0]['competitors']
        home = next((c for c in comp if c['homeAway'] == 'home'), comp[0])
        away = next((c for c in comp if c['homeAway'] == 'away'), comp[1])
        match_data.append({
            'id': m['id'],
            'name': f"{home['team']['name']} vs {away['team']['name']}"
        })
    print('Data payload prepared. Calling global_save_section...')
    await global_save_section(toto_key, {
        'p1': TARGET_USER_ID,
        'p2': chosen_opp,
        'matches': [m['id'] for m in all_matches],
        'match_data': match_data,
        'picks': {},
        'resolved': False
    })
    print('Saved to DB!')

asyncio.run(test_toto())
