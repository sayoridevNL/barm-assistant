import os
import subprocess
import sys
from flask import Flask, request, jsonify, render_template, session, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

bot_process = None

def is_bot_running():
    global bot_process
    if bot_process is None:
        return False
    return bot_process.poll() is None

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
    return jsonify({'running': is_bot_running()})

@app.route('/api/start', methods=['POST'])
def start_bot():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    global bot_process
    if is_bot_running():
        return jsonify({'success': False, 'message': 'Bot is already running'})
    
    try:
        # Start the bot process
        bot_process = subprocess.Popen([sys.executable, 'launcher.py'])
        return jsonify({'success': True, 'message': 'Bot started'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    global bot_process
    if not is_bot_running():
        return jsonify({'success': False, 'message': 'Bot is not running'})
    
    try:
        bot_process.terminate()
        bot_process.wait(timeout=5)
        bot_process = None
        return jsonify({'success': True, 'message': 'Bot stopped'})
    except Exception as e:
        if bot_process:
            bot_process.kill()
        bot_process = None
        return jsonify({'success': False, 'message': str(e)}), 500

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
    app.run(host='0.0.0.0', port=5000, debug=True)
