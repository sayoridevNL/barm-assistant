import os
import subprocess
import sys
import json
import threading
import time
import requests
import pymongo
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, session, send_from_directory, redirect
from dotenv import load_dotenv

load_dotenv()

import asyncio
import threading
_server_loop = None
_loop_started = False
_loop_lock = threading.Lock()

def _run_server_loop():
    global _server_loop
    _server_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_server_loop)
    _server_loop.run_forever()

def run_async(coro):
    global _loop_started, _server_loop
    if not _loop_started:
        with _loop_lock:
            if not _loop_started:
                threading.Thread(target=_run_server_loop, daemon=True).start()
                _loop_started = True
                import time
                while _server_loop is None or not _server_loop.is_running():
                    time.sleep(0.01)
    future = asyncio.run_coroutine_threadsafe(coro, _server_loop)
    return future.result()
MONGO_URI = os.getenv("MONGODB_URI")
mongo_client = None
mongo_db = None

app = Flask(__name__, static_folder='static', template_folder='templates')
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key_barm_os_2026_fallback')

DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI', 'http://localhost:5000/api/auth/callback')
ADMIN_IDS = ["1043235209639886972", "1480592862734323763", "879118301169602570"]
TOTO_PARTICIPANT_IDS = {
    "1158703899843231836", "899372657554894909", "907956482207776778",
    "315845909533556741", "787681263267479572", "1513484108033163309",
    "879118301169602570", "748110757400674324", "431864554910121994",
}
NETHERLANDS_TZ = ZoneInfo("Europe/Amsterdam")

BOTS = [
    "music_bot",
    "moderation_bot",
    "community_bot",
    "gambling_bot",
    "umamusume_bot",
    "general_bot",
]

bot_processes = {bot: None for bot in BOTS}
bot_lock = threading.Lock()
bot_restart_delays = {bot: 10 for bot in BOTS}
bot_last_start = {bot: 0 for bot in BOTS}

def is_bot_running(bot_name):
    process = bot_processes.get(bot_name)
    if process is None:
        return False
    return process.poll() is None

def start_single_bot(bot_name):
    if is_bot_running(bot_name):
        # Reset delay if it's successfully running for a while
        if time.time() - bot_last_start.get(bot_name, 0) > 60:
            bot_restart_delays[bot_name] = 10
        return False, "Already running"
        
    now = time.time()
    last = bot_last_start.get(bot_name, 0)
    delay = bot_restart_delays.get(bot_name, 10)
    
    if now - last < delay:
        return False, f"Cooldown active (waiting {int(delay - (now - last))}s)"
        
    bot_last_start[bot_name] = now
    bot_restart_delays[bot_name] = min(delay * 2, 600)  # Max 10 mins
    
    try:
        # Start the bot process using launcher.py with the bot name as an argument
        process = subprocess.Popen([sys.executable, 'launcher.py', bot_name])
        bot_processes[bot_name] = process
        return True, "Bot started"
    except Exception as e:
        return False, str(e)

def stop_single_bot(bot_name):
    process = bot_processes.get(bot_name)
    if not is_bot_running(bot_name):
        return False, "Not running"
    try:
        process.terminate()
        process.wait(timeout=5)
        bot_processes[bot_name] = None
        return True, "Bot stopped"
    except Exception as e:
        if process:
            process.kill()
        bot_processes[bot_name] = None
        return False, str(e)

# --- Automatic Startup ---
# We use a simple lock file to prevent multiple Gunicorn workers from spawning duplicate bots
LOCK_FILE = '/tmp/barm_bots_started.lock'
if not os.path.exists(LOCK_FILE):
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write('started')
        
        # Stagger the initial startup by 5 seconds per bot to prevent Discord Gateway IDENTIFY rate limits
        import threading
        def staggered_startup():
            for bot in BOTS:
                start_single_bot(bot)
                time.sleep(5)
                
        threading.Thread(target=staggered_startup, daemon=True).start()
    except Exception:
        pass


@app.route('/')
def index():
    # Watchdog: Pinging the website automatically restarts any dead bots
    def watchdog_restart():
        with bot_lock:
            for bot in BOTS:
                if not is_bot_running(bot):
                    started, _ = start_single_bot(bot)
                    if started:
                        time.sleep(5)
    
    import threading
    threading.Thread(target=watchdog_restart, daemon=True).start()
    
    return render_template('index.html', user_id=session.get('user_id'), username=session.get('username'), avatar=session.get('avatar'), is_admin=is_admin())

def is_admin():
    return session.get('user_id') in ADMIN_IDS

@app.route('/api/auth/login')
def login():
    if not DISCORD_CLIENT_ID:
        return "Discord OAuth not configured", 500
    
    auth_url = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={requests.utils.quote(DISCORD_REDIRECT_URI)}&response_type=code&scope=identify"
    return redirect(auth_url)

@app.route('/api/auth/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "Missing code", 400
        
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI
    }
    
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    r = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
    if not r.ok:
        return f"Failed to get token: {r.text}", 400
        
    token_data = r.json()
    access_token = token_data['access_token']
    
    user_r = requests.get('https://discord.com/api/users/@me', headers={
        'Authorization': f"Bearer {access_token}"
    })
    
    if not user_r.ok:
        return "Failed to get user info", 400
        
    user_data = user_r.json()
    session['user_id'] = user_data['id']
    session['username'] = user_data['username']
    session['avatar'] = user_data.get('avatar')
    
    return redirect('/')

@app.route('/api/auth/logout')
def logout():
    session.clear()



def _get_mongo_db_sync():
    global mongo_client, mongo_db
    if mongo_db is None and MONGO_URI:
        import pymongo
        mongo_client = pymongo.MongoClient(MONGO_URI)
        mongo_db = mongo_client["barm_os"]
    return mongo_db

def db_get_section_sync(guild_id, section):
    db = _get_mongo_db_sync()
    if db is not None:
        doc = db.guilds.find_one({"_id": str(guild_id)})
        if doc: return doc.get(section, {})
    return {}

def db_save_section_sync(guild_id, section, data):
    db = _get_mongo_db_sync()
    if db is not None:
        db.guilds.update_one({"_id": str(guild_id)}, {"$set": {section: data}}, upsert=True)

def get_global_section_sync(section):
    db = _get_mongo_db_sync()
    if db is not None:
        doc = db.global_data.find_one({"_id": section})
        return doc.get("data", {}) if doc else {}
    try:
        with open('data/global.json', 'r', encoding='utf-8') as f:
            return json.load(f).get(section, {})
    except:
        return {}

def save_global_section_sync(section, data):
    db = _get_mongo_db_sync()
    if db is not None:
        db.global_data.update_one({"_id": section}, {"$set": {"data": data}}, upsert=True)
    else:
        try:
            with open('data/global.json', 'r', encoding='utf-8') as f:
                d = json.load(f)
        except:
            d = {}
        d[section] = data
        with open('data/global.json', 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=4)

@app.route('/api/user/stats', methods=['GET'])
def user_stats():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
        
    quotes = get_global_section_sync('quotes').get(user_id, {}).get('stars', 0)
    user_eco = get_global_section_sync('economy').get(user_id, {})
    sayories = user_eco.get('balance', 0)
    free_haru_coins = user_eco.get('free_haru_coins', 0)
    paid_haru_coins = user_eco.get('paid_haru_coins', 0)
    user_umas = get_global_section_sync('uma_inventory').get(user_id, {}).get('umas', [])
    user_support = get_global_section_sync('uma_support_inventory').get(user_id, {}).get('cards', [])
    
    return jsonify({
        'user_id': user_id,
        'username': session.get('username'),
        'avatar': session.get('avatar'),
        'is_admin': is_admin(),
        'stats': {
            'quotes': quotes,
            'sayories': sayories,
            'free_haru_coins': free_haru_coins,
            'paid_haru_coins': paid_haru_coins,
            'umamusume': len(user_umas),
            'umas_list': user_umas,
            'support_cards': len(user_support),
            'support_cards_list': user_support
        }
    })

@app.route('/api/quotes', methods=['GET'])
def get_user_quotes():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    qhist = get_global_section_sync('quote_history')
    user_quotes = qhist.get(user_id, [])
    
    return jsonify({'quotes': user_quotes})

USERNAME_CACHE = {}
def get_discord_username(uid):
    if uid in USERNAME_CACHE: return USERNAME_CACHE[uid]
    token = os.getenv("GENERAL_BOT_TOKEN")
    if not token: return f"User {uid}"
    try:
        import requests
        r = requests.get(f'https://discord.com/api/v10/users/{uid}', headers={'Authorization': f'Bot {token.strip()}'})
        if r.status_code == 200:
            name = r.json().get('username', f"User {uid}")
            USERNAME_CACHE[uid] = name
            return name
    except: pass
    return f"User {uid}"

@app.route('/api/admin/publish_embed', methods=['POST'])
def publish_embed():
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    title = data.get('title', '').strip()
    desc = data.get('desc', '').strip()
    color = data.get('color', '').strip()
    image = data.get('image', '').strip()
    footer = data.get('footer', '').strip()

    if not title and not desc:
        return jsonify({'error': 'Title or description required'}), 400

    if mongo_db is not None:
        import time
        mongo_db.broadcast_queue.insert_one({
            'title': title,
            'desc': desc,
            'color': color,
            'image': image,
            'footer': footer,
            'timestamp': int(time.time())
        })
        return jsonify({'message': 'Broadcast queued successfully!'})
    else:
        return jsonify({'error': 'MongoDB is not connected. Broadcasts require MongoDB.'}), 500

@app.route('/api/uma/train', methods=['POST'])
def uma_train():
    user_id = session.get('user_id')
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    uma_id = data.get('uma_id')
    
    if not uma_id: return jsonify({'error': 'Missing uma_id'}), 400
    
    inv = get_global_section_sync('uma_inventory')
    user_inv = inv.get(user_id, {})
    umas = user_inv.get('umas', [])
    
    uma = next((u for u in umas if u['id'] == uma_id), None)
    if not uma: return jsonify({'error': 'Uma not found'}), 404
    
    import time
    now = int(time.time())
    if uma.get('training_end') and now < uma['training_end']:
        return jsonify({'error': 'Already training!'}), 400
        
    uma['training_start'] = now
    uma['training_end'] = now + 3600  # 1 hour
    uma['training_parents'] = data.get('parents', [])
    uma['training_supports'] = data.get('supports', [])
    
    save_global_section_sync('uma_inventory', inv)
    return jsonify({'success': True, 'training_end': uma['training_end']})

@app.route('/api/uma/finish_train', methods=['POST'])
def uma_finish_train():
    user_id = session.get('user_id')
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    uma_id = data.get('uma_id')
    if not uma_id: return jsonify({'error': 'Missing uma_id'}), 400
    
    inv = get_global_section_sync('uma_inventory')
    user_inv = inv.get(user_id, {})
    umas = user_inv.get('umas', [])
    
    uma = next((u for u in umas if u['id'] == uma_id), None)
    if not uma: return jsonify({'error': 'Uma not found'}), 404
    
    import time
    now = int(time.time())
    if not uma.get('training_end'):
        return jsonify({'error': 'Not training'}), 400
        
    if now < uma['training_end']:
        return jsonify({'error': 'Training not finished yet'}), 400
        
    # Calculate bonuses
    # For now, give a flat boost plus the support card bonuses
    bonus_speed = uma.get('speed_bonus', 0)
    bonus_stamina = uma.get('stamina_bonus', 0)
    bonus_power = uma.get('power_bonus', 0)
    bonus_guts = uma.get('guts_bonus', 0)
    bonus_wit = uma.get('wit_bonus', 0)
    
    # We will grant base points + % growth
    uma['speed'] = uma.get('speed', 1) + 20 + int(20 * (bonus_speed/100))
    uma['stamina'] = uma.get('stamina', 1) + 20 + int(20 * (bonus_stamina/100))
    uma['power'] = uma.get('power', 1) + 20 + int(20 * (bonus_power/100))
    uma['guts'] = uma.get('guts', 1) + 20 + int(20 * (bonus_guts/100))
    uma['wit'] = uma.get('wit', 1) + 20 + int(20 * (bonus_wit/100))
    
    # Optional: fetch support card data to add extra stats, simplified for now.
    
    del uma['training_start']
    del uma['training_end']
    
    save_global_section_sync('uma_inventory', inv)
    return jsonify({'success': True, 'uma': uma})

@app.route('/api/toto/battle', methods=['GET'])
def get_toto_battle():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    if user_id not in TOTO_PARTICIPANT_IDS:
        return jsonify({'eligible': False, 'active': False})
        
    import time, json
    from datetime import datetime
    from pathlib import Path
    
    today_str = datetime.now(NETHERLANDS_TZ).strftime("%Y%m%d")
    toto_key = f"toto_battle_{today_str}"
    
    battle = {}
    if mongo_db is not None:
        doc = mongo_db.global_data.find_one({"_id": toto_key})
        if doc: battle = doc.get("data", {})
    else:
        from shared import _load_global_sync
        battle = _load_global_sync().get(toto_key, {})
        
    if not battle:
        return jsonify({'eligible': True, 'active': False})
        
    if int(user_id) not in [int(battle.get('p1', 0)), int(battle.get('p2', 0))]:
        return jsonify({'eligible': True, 'active': False, 'message': 'A battle is running today, but you were not selected.'})
        
    # Return battle data without opponent's picks to prevent cheating
    my_picks = battle.get('picks', {}).get(str(user_id), {})
    return jsonify({
        'eligible': True,
        'active': True,
        'resolved': battle.get('resolved', False),
        'match_data': battle.get('match_data', []),
        'my_picks': my_picks
    })

@app.route('/api/toto/predict', methods=['POST'])
def submit_toto_predict():
    user_id = session.get('user_id')
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    if user_id not in TOTO_PARTICIPANT_IDS:
        return jsonify({'error': 'You are not eligible for Prediction Battles'}), 403
    
    data = request.get_json(silent=True) or {}
    picks = data.get('picks', {})
    if not isinstance(picks, dict):
        return jsonify({'error': 'Predictions must be an object'}), 400
    
    import time, json
    from datetime import datetime
    today_str = datetime.now(NETHERLANDS_TZ).strftime("%Y%m%d")
    toto_key = f"toto_battle_{today_str}"
    
    if mongo_db is not None:
        doc = mongo_db.global_data.find_one({"_id": toto_key})
        battle = doc.get("data", {}) if doc else {}
        if not battle or battle.get('resolved'): return jsonify({'error': 'Battle not active or already resolved'}), 400
        if int(user_id) not in [int(battle.get('p1', 0)), int(battle.get('p2', 0))]: return jsonify({'error': 'Not in battle'}), 403
        
        valid_match_ids = {str(match['id']) for match in battle.get('match_data', [])}
        if set(map(str, picks)) != valid_match_ids or any(choice not in {'1', 'X', '2'} for choice in picks.values()):
            return jsonify({'error': 'Choose one valid result for every match'}), 400
        battle.setdefault('picks', {})[str(user_id)] = {str(match_id): choice for match_id, choice in picks.items()}
        mongo_db.global_data.update_one({"_id": toto_key}, {"$set": {"data": battle}}, upsert=True)
    else:
        from shared import _load_global_sync, _save_global_sync, _global_lock
        gl_data = _load_global_sync()
        battle = gl_data.get(toto_key, {})
        if not battle or battle.get('resolved'): return jsonify({'error': 'Battle not active or already resolved'}), 400
        if int(user_id) not in [int(battle.get('p1', 0)), int(battle.get('p2', 0))]: return jsonify({'error': 'Not in battle'}), 403
        
        valid_match_ids = {str(match['id']) for match in battle.get('match_data', [])}
        if set(map(str, picks)) != valid_match_ids or any(choice not in {'1', 'X', '2'} for choice in picks.values()):
            return jsonify({'error': 'Choose one valid result for every match'}), 400
        battle.setdefault('picks', {})[str(user_id)] = {str(match_id): choice for match_id, choice in picks.items()}
        gl_data[toto_key] = battle
        _save_global_sync(gl_data)
        
    return jsonify({'success': True, 'picks': battle['picks'][str(user_id)]})


@app.route('/api/suggest', methods=['POST'])
def submit_suggestion():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.json
    suggestion = data.get('suggestion', '').strip()
    if not suggestion:
        return jsonify({'error': 'Suggestion cannot be empty'}), 400
    if len(suggestion) > 1000:
        return jsonify({'error': 'Suggestion too long'}), 400
        
    import time
    import json
    from pathlib import Path
    
    # Simple JSON fallback for web suggestions since shared.py's lock isn't thread-safe for flask
    WEB_SUGG_FILE = Path(__file__).parent / "data" / "web_suggestions.json"
    
    if mongo_db is not None:
        last_submit_doc = mongo_db.cooldowns.find_one({"_id": f"sugg_cd_{user_id}"})
        last_submit = last_submit_doc["time"] if last_submit_doc else 0
        if time.time() - last_submit < 3600:
            rem = int(3600 - (time.time() - last_submit))
            return jsonify({'error': f'Cooldown active. Try again in {rem//60} minutes.'}), 429
            
        mongo_db.cooldowns.update_one({"_id": f"sugg_cd_{user_id}"}, {"$set": {"time": time.time()}}, upsert=True)
        mongo_db.web_suggestions.insert_one({
            "user_id": user_id,
            "suggestion": suggestion,
            "timestamp": time.time()
        })
    else:
        # Fallback to JSON
        WEB_SUGG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if WEB_SUGG_FILE.exists():
            try:
                with open(WEB_SUGG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except: pass
            
        last_submit = data.get("cooldowns", {}).get(str(user_id), 0)
        if time.time() - last_submit < 3600:
            rem = int(3600 - (time.time() - last_submit))
            return jsonify({'error': f'Cooldown active. Try again in {rem//60} minutes.'}), 429
            
        data.setdefault("cooldowns", {})[str(user_id)] = time.time()
        data.setdefault("queue", []).append({
            "user_id": user_id,
            "suggestion": suggestion,
            "timestamp": time.time()
        })
        with open(WEB_SUGG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    
    return jsonify({'success': True})

@app.route('/api/leaderboards', methods=['GET'])
def get_leaderboards():
    if not session.get('user_id'): return jsonify({'error': 'Unauthorized'}), 401
        
    economy = get_global_section_sync('economy')
    quotes = get_global_section_sync('quotes')
    
    sayories_board = sorted([(uid, data.get('balance', 0)) for uid, data in economy.items()], key=lambda x: x[1], reverse=True)[:10]
    quotes_board = sorted([(uid, data.get('stars', 0)) for uid, data in quotes.items()], key=lambda x: x[1], reverse=True)[:10]
    
    s_res = [{"user_id": u, "username": get_discord_username(u), "score": s} for u, s in sayories_board]
    q_res = [{"user_id": u, "username": get_discord_username(u), "score": s} for u, s in quotes_board]
    
    return jsonify({"sayories": s_res, "quotes": q_res})

@app.route('/api/status', methods=['GET'])
def get_status():
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    
    statuses = {bot: is_bot_running(bot) for bot in BOTS}
    return jsonify({'running': any(statuses.values()), 'bots': statuses})

@app.route('/api/start/<bot_name>', methods=['POST'])
def start_bot_route(bot_name):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    if bot_name not in BOTS:
        return jsonify({'success': False, 'message': 'Invalid bot name'}), 400
        
    with bot_lock:
        success, msg = start_single_bot(bot_name)
    return jsonify({'success': success, 'message': msg}), 200 if success else 500

@app.route('/api/stop/<bot_name>', methods=['POST'])
def stop_bot_route(bot_name):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    if bot_name not in BOTS:
        return jsonify({'success': False, 'message': 'Invalid bot name'}), 400
        
    with bot_lock:
        success, msg = stop_single_bot(bot_name)
    return jsonify({'success': success, 'message': msg}), 200 if success else 500

@app.route('/api/presence/<bot_name>', methods=['POST'])
def set_presence(bot_name):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    if bot_name not in BOTS:
        return jsonify({'success': False, 'message': 'Invalid bot name'}), 400
        
    data = request.json
    presence = data.get('presence', '').strip()
    
    # Save presence to a JSON file that the bots will read periodically
    presence_file = 'presence.json'
    try:
        if os.path.exists(presence_file):
            with open(presence_file, 'r', encoding='utf-8') as f:
                presences = json.load(f)
        else:
            presences = {}
    except:
        presences = {}
        
    presences[bot_name] = presence
    
    with open(presence_file, 'w', encoding='utf-8') as f:
        json.dump(presences, f)
        
    return jsonify({'success': True})

@app.route('/api/presence', methods=['GET'])
def get_presences():
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
        
    try:
        if os.path.exists('presence.json'):
            with open('presence.json', 'r', encoding='utf-8') as f:
                presences = json.load(f)
        else:
            presences = {}
    except:
        presences = {}
    return jsonify({'presences': presences})

@app.route('/api/files', methods=['GET'])
def list_files():
    if not is_admin(): return jsonify({'success': False}), 401
    files = [f for f in os.listdir('.') if f.endswith('.py') or f.endswith('.txt')]
    return jsonify({'files': sorted(files)})

@app.route('/api/files/<path:filename>', methods=['GET'])
def get_file(filename):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not filename.endswith('.py') or '..' in filename:
        return jsonify({'error': 'Invalid file'}), 400
        
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<path:filename>', methods=['POST'])
def save_file(filename):
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 401
        
    if not filename.endswith('.py') or '..' in filename:
        return jsonify({'error': 'Invalid file'}), 400
        
    data = request.json
    content = data.get('content')
    
    if content is None:
        return jsonify({'error': 'No content provided'}), 400
        
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- CARDS GACHA ROUTES ---
import asyncio
import shared
CARDS_GUILD_ID = 1049396166250475612

def is_cards_admin():
    uid = session.get('user_id')
    return uid in ["1043235209639886972", "879118301169602570"]

@app.route('/api/cards/settings', methods=['GET', 'POST'])
def cards_settings():
    if request.method == 'POST':
        if not is_cards_admin(): return jsonify({'error': 'Unauthorized'}), 401
        data = request.json or {}
        db_save_section_sync(CARDS_GUILD_ID, 'cards_settings', data)
        return jsonify({'success': True})
    settings = db_get_section_sync(CARDS_GUILD_ID, 'cards_settings')
    return jsonify(settings)

@app.route('/api/cards/rarities', methods=['GET', 'POST'])
def cards_rarities():
    if request.method == 'POST':
        if not is_cards_admin(): return jsonify({'error': 'Unauthorized'}), 401
        data = request.json or {}
        db_save_section_sync(CARDS_GUILD_ID, 'cards_rarities', data)
        return jsonify({'success': True})
    rarities = db_get_section_sync(CARDS_GUILD_ID, 'cards_rarities')
    return jsonify(rarities)

@app.route('/api/cards/templates', methods=['GET', 'POST'])
def cards_templates():
    if request.method == 'POST':
        if not is_cards_admin(): return jsonify({'error': 'Unauthorized'}), 401
        data = request.json or []
        db_save_section_sync(CARDS_GUILD_ID, 'cards_templates', data)
        return jsonify({'success': True})
    templates = db_get_section_sync(CARDS_GUILD_ID, 'cards_templates')
    return jsonify(templates)

@app.route('/api/cards/inventory', methods=['GET'])
def cards_inventory():
    user_id = session.get('user_id')
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    inv = db_get_section_sync(CARDS_GUILD_ID, 'cards_inventory').get(str(user_id), [])
    return jsonify(inv)

@app.route('/api/cards/pull', methods=['POST'])
def cards_pull():
    user_id = session.get('user_id')
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    count = int(data.get('count', 1))
    if count not in [1, 3, 5, 10, 20]:
        count = 1
        
    settings = db_get_section_sync(CARDS_GUILD_ID, 'cards_settings')
    if not settings.get('enabled', True):
        return jsonify({'error': 'Card pulls are currently disabled'}), 400
        
    cost = 100 * count
    sayories = get_global_section_sync('economy').get(str(user_id), {}).get('balance', 0)
    if sayories < cost:
        return jsonify({'error': f'Not enough Sayories ({cost} required)'}), 400
        
    templates = db_get_section_sync(CARDS_GUILD_ID, 'cards_templates')
    if not templates:
        return jsonify({'error': 'No cards available to pull'}), 400
        
    # Get rarities for weighted drops
    rarities = db_get_section_sync(CARDS_GUILD_ID, 'cards_rarities')
    if isinstance(rarities, dict): rarities = rarities.get("rarities", [])
    if not rarities:
        rarities = [
            {'name': 'C', 'chance': 45.0}, {'name': 'UC', 'chance': 30.0},
            {'name': 'R', 'chance': 15.0}, {'name': 'SR', 'chance': 6.0},
            {'name': 'SSR', 'chance': 3.0}, {'name': 'SSL', 'chance': 0.9},
            {'name': 'USL', 'chance': 0.1}
        ]
        
    # Group templates by rarity
    from collections import defaultdict
    cards_by_rarity = defaultdict(list)
    for c in templates:
        cards_by_rarity[c.get('rarity', 'C')].append(c)
        
    import random, time, uuid
    
    pulled_items = []
    pulled_templates = []
    
    for _ in range(count):
        # Roll for rarity
        rand_val = random.uniform(0, 100)
        cumulative = 0.0
        selected_rarity = None
        
        for r in rarities:
            r_name = r.get('name')
            r_chance = float(r.get('chance', 0))
            if r_chance <= 0: continue
            
            cumulative += r_chance
            if rand_val <= cumulative:
                selected_rarity = r_name
                break
                
        if not selected_rarity or not cards_by_rarity.get(selected_rarity):
            # Fallback if rng failed or no cards in that rarity
            card = random.choice(templates)
        else:
            card = random.choice(cards_by_rarity[selected_rarity])
            
        pulled_templates.append(card)
        new_item = {'id': str(uuid.uuid4()), 'template_id': card.get('id', str(uuid.uuid4())), 'timestamp': int(time.time()), 'locked': False}
        pulled_items.append(new_item)
        
    _eco=get_global_section_sync('economy'); _usr=_eco.setdefault(str(user_id),{}); _usr['balance']=_usr.get('balance',0) - cost; save_global_section_sync('economy', _eco)
    
    inv = db_get_section_sync(CARDS_GUILD_ID, 'cards_inventory').get(str(user_id), [])
    cards_list = inv.get('cards', [])
    cards_list.extend(pulled_items)
    inv['cards'] = cards_list
    _invs=db_get_section_sync(CARDS_GUILD_ID, 'cards_inventory'); _invs[str(user_id)]=inv; db_save_section_sync(CARDS_GUILD_ID, 'cards_inventory', _invs)
    
    new_sayories = get_global_section_sync('economy').get(str(user_id), {}).get('balance', 0)
    
    return jsonify({'success': True, 'pulled_cards': pulled_items, 'templates': pulled_templates, 'new_balance': new_sayories})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port, debug=False)
