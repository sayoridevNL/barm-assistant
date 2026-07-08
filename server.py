import os
import subprocess
import sys
import json
import threading
from flask import Flask, request, jsonify, render_template, session, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

BOTS = [
    "music_bot",
    "moderation_bot",
    "community_bot",
    "gambling_bot",
    "umamusume_bot",
    "general_bot"
]

bot_processes = {bot: None for bot in BOTS}
bot_lock = threading.Lock()

def is_bot_running(bot_name):
    process = bot_processes.get(bot_name)
    if process is None:
        return False
    return process.poll() is None

def start_single_bot(bot_name):
    if is_bot_running(bot_name):
        return False, "Already running"
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
        for bot in BOTS:
            start_single_bot(bot)
    except Exception:
        pass


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('password') == ADMIN_PASSWORD:
        session['authenticated'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid password'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('authenticated', None)
    return jsonify({'success': True})

@app.route('/api/status', methods=['GET'])
def get_status():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    statuses = {bot: is_bot_running(bot) for bot in BOTS}
    return jsonify({'running': any(statuses.values()), 'bots': statuses})

@app.route('/api/start/<bot_name>', methods=['POST'])
def start_bot_route(bot_name):
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    if bot_name not in BOTS:
        return jsonify({'success': False, 'message': 'Invalid bot name'}), 400
        
    with bot_lock:
        success, msg = start_single_bot(bot_name)
    return jsonify({'success': success, 'message': msg}), 200 if success else 500

@app.route('/api/stop/<bot_name>', methods=['POST'])
def stop_bot_route(bot_name):
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    if bot_name not in BOTS:
        return jsonify({'success': False, 'message': 'Invalid bot name'}), 400
        
    with bot_lock:
        success, msg = stop_single_bot(bot_name)
    return jsonify({'success': success, 'message': msg}), 200 if success else 500

@app.route('/api/presence/<bot_name>', methods=['POST'])
def set_presence(bot_name):
    if not session.get('authenticated'):
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
    if not session.get('authenticated'):
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
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    files = [f for f in os.listdir('.') if f.endswith('.py')]
    return jsonify({'files': files})

@app.route('/api/files/<path:filename>', methods=['GET'])
def get_file(filename):
    if not session.get('authenticated'):
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
    if not session.get('authenticated'):
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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port, debug=False)
