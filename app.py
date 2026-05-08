from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, emit
import requests
import json
import threading
import time
import os
import sys
import tempfile
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from flask_cors import CORS

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

# Папка для данных пользователей
USERS_DIR = os.path.join(os.getcwd(), "user_data")
os.makedirs(USERS_DIR, exist_ok=True)

class UserManager:
    @staticmethod
    def get_user_file(user_id):
        return os.path.join(USERS_DIR, f"{user_id}.json")
    
    @staticmethod
    def create_user(username, password):
        # Проверяем, существует ли пользователь
        for filename in os.listdir(USERS_DIR):
            if filename.endswith('.json'):
                with open(os.path.join(USERS_DIR, filename), 'r') as f:
                    user_data = json.load(f)
                    if user_data["username"] == username:
                        return None, None
        
        user_id = secrets.token_hex(16)
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
        
        user_data = {
            "id": user_id,
            "username": username,
            "password_hash": password_hash,
            "salt": salt,
            "created_at": datetime.now().isoformat(),
            "bots": {},
            "settings": {"theme": "dark", "notifications": True, "sound": True},
            "session_token": secrets.token_hex(32)
        }
        
        with open(UserManager.get_user_file(user_id), 'w') as f:
            json.dump(user_data, f, indent=4)
        
        return user_id, user_data["session_token"]
    
    @staticmethod
    def verify_user(username, password):
        for filename in os.listdir(USERS_DIR):
            if filename.endswith('.json'):
                with open(os.path.join(USERS_DIR, filename), 'r') as f:
                    user_data = json.load(f)
                    if user_data["username"] == username:
                        password_hash = hashlib.pbkdf2_hmac(
                            'sha256', 
                            password.encode(), 
                            user_data["salt"].encode(), 
                            100000
                        ).hex()
                        if password_hash == user_data["password_hash"]:
                            new_token = secrets.token_hex(32)
                            user_data["session_token"] = new_token
                            with open(UserManager.get_user_file(user_data["id"]), 'w') as f:
                                json.dump(user_data, f)
                            return user_data["id"], new_token
        return None, None
    
    @staticmethod
    def get_user_by_token(token):
        if not token:
            return None
        for filename in os.listdir(USERS_DIR):
            if filename.endswith('.json'):
                with open(os.path.join(USERS_DIR, filename), 'r') as f:
                    user_data = json.load(f)
                    if user_data.get("session_token") == token:
                        return user_data
        return None
    
    @staticmethod
    def save_user_data(user_data):
        with open(UserManager.get_user_file(user_data["id"]), 'w') as f:
            json.dump(user_data, f, indent=4)

# Активные соединения и поллеры
active_connections = {}
user_pollers = {}

class UserBotPoller:
    def __init__(self, user_id, token, socketio_instance):
        self.user_id = user_id
        self.token = token
        self.socketio = socketio_instance
        self.running = True
        self.last_update_id = 0
        
    def start(self):
        thread = threading.Thread(target=self._poll, daemon=True)
        thread.start()
        
    def _poll(self):
        while self.running:
            try:
                offset = self.last_update_id + 1
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {"offset": offset, "timeout": 10}
                r = requests.get(url, params=params, timeout=15)
                result = r.json()
                
                if result.get("ok") and result["result"]:
                    for update in result["result"]:
                        self.process_update(update)
                        self.last_update_id = update["update_id"]
            except Exception as e:
                print(f"Polling error for user {self.user_id}: {e}")
            time.sleep(1)
            
    def process_update(self, update):
        message = update.get("message")
        if not message:
            return
            
        chat_id = str(message["chat"]["id"])
        chat_name = message["chat"].get("title") or message.get("from", {}).get("first_name", "Unknown")
        text = message.get("text", "📎 Вложение")
        
        # Ищем пользователя по user_id
        user_data = None
        for filename in os.listdir(USERS_DIR):
            if filename.endswith('.json'):
                with open(os.path.join(USERS_DIR, filename), 'r') as f:
                    data = json.load(f)
                    if data["id"] == self.user_id:
                        user_data = data
                        break
        
        if not user_data:
            return
            
        if self.token not in user_data["bots"]:
            user_data["bots"][self.token] = {"chats": {}, "history": {}}
        
        if chat_id not in user_data["bots"][self.token]["chats"]:
            user_data["bots"][self.token]["chats"][chat_id] = {"name": chat_name, "unread": 0}
            user_data["bots"][self.token]["history"][chat_id] = []
            
        new_msg = {
            "text": text,
            "is_my": False,
            "time": datetime.now().isoformat(),
            "sender": chat_name
        }
        user_data["bots"][self.token]["history"][chat_id].append(new_msg)
        user_data["bots"][self.token]["chats"][chat_id]["unread"] += 1
        
        UserManager.save_user_data(user_data)
        
        self.socketio.emit('new_message', {
            'user_id': self.user_id,
            'token': self.token,
            'chat_id': chat_id,
            'message': new_msg
        }, room=self.user_id)
        
    def stop(self):
        self.running = False

# REST API endpoints
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400
    
    if len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400
    
    user_id, token = UserManager.create_user(username, password)
    if not user_id:
        return jsonify({'error': 'Username already exists'}), 400
    
    return jsonify({
        'success': True, 
        'username': username,
        'token': token,
        'user_id': user_id
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    user_id, token = UserManager.verify_user(username, password)
    if user_id:
        return jsonify({
            'success': True, 
            'username': username,
            'token': token,
            'user_id': user_id
        })
    
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    return jsonify({'success': True})

@app.route('/api/check_auth', methods=['POST'])
def check_auth():
    data = request.json
    token = data.get('token')
    if token:
        user_data = UserManager.get_user_by_token(token)
        if user_data:
            return jsonify({'authenticated': True, 'username': user_data['username']})
    return jsonify({'authenticated': False})

@app.route('/api/sync', methods=['POST'])
def sync_data():
    data = request.json
    token = data.get('token')
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'bots': user_data.get('bots', {}),
        'settings': user_data.get('settings', {})
    })

@app.route('/api/bots', methods=['POST'])
def get_bots():
    data = request.json
    token = data.get('token')
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    bot_list = []
    for bot_token, info in user_data.get('bots', {}).items():
        bot_list.append({
            'token': bot_token,
            'username': info.get('username', 'Unknown'),
            'chats_count': len(info.get('chats', {})),
            'unread_total': sum(c.get('unread', 0) for c in info.get('chats', {}).values())
        })
    return jsonify(bot_list)

@app.route('/api/bots/add', methods=['POST'])
def add_bot():
    data = request.json
    token = data.get('token')
    bot_token = data.get('bot_token')
    
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    if not bot_token:
        return jsonify({'error': 'Bot token is required'}), 400
        
    try:
        r = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
        result = r.json()
        
        if result.get("ok"):
            username = result["result"]["username"]
            
            if bot_token not in user_data.get('bots', {}):
                user_data.setdefault('bots', {})[bot_token] = {
                    "username": username,
                    "chats": {},
                    "history": {}
                }
                
                UserManager.save_user_data(user_data)
                
                # Запускаем поллер для этого бота
                if user_data['id'] not in user_pollers:
                    user_pollers[user_data['id']] = {}
                poller = UserBotPoller(user_data['id'], bot_token, socketio)
                poller.start()
                user_pollers[user_data['id']][bot_token] = poller
            
            return jsonify({'success': True, 'username': username})
        else:
            return jsonify({'error': 'Invalid token'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bots/remove', methods=['POST'])
def remove_bot():
    data = request.json
    token = data.get('token')
    bot_token = data.get('bot_token')
    
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    if bot_token in user_data.get('bots', {}):
        del user_data['bots'][bot_token]
        UserManager.save_user_data(user_data)
        
        if user_data['id'] in user_pollers and bot_token in user_pollers[user_data['id']]:
            user_pollers[user_data['id']][bot_token].stop()
            del user_pollers[user_data['id']][bot_token]
        
        return jsonify({'success': True})
    return jsonify({'error': 'Bot not found'}), 404

@app.route('/api/chats', methods=['POST'])
def get_chats():
    data = request.json
    token = data.get('token')
    bot_token = data.get('bot_token')
    
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    if bot_token in user_data.get('bots', {}):
        chats = list(user_data['bots'][bot_token].get('chats', {}).items())
        chat_list = [{'id': cid, 'name': info['name'], 'unread': info.get('unread', 0)} 
                     for cid, info in chats]
        return jsonify(chat_list)
    return jsonify([])

@app.route('/api/messages', methods=['POST'])
def get_messages():
    data = request.json
    token = data.get('token')
    bot_token = data.get('bot_token')
    chat_id = data.get('chat_id')
    
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    if bot_token in user_data.get('bots', {}):
        history = user_data['bots'][bot_token].get('history', {}).get(chat_id, [])
        if chat_id in user_data['bots'][bot_token].get('chats', {}):
            user_data['bots'][bot_token]['chats'][chat_id]['unread'] = 0
            UserManager.save_user_data(user_data)
        return jsonify(history)
    return jsonify([])

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    token = data.get('token')
    bot_token = data.get('bot_token')
    chat_id = data.get('chat_id')
    text = data.get('text', '').strip()
    file_data = data.get('file')
    
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    if not bot_token or not chat_id or (not text and not file_data):
        return jsonify({'error': 'Missing parameters'}), 400
        
    try:
        if file_data:
            import base64
            file_bytes = base64.b64decode(file_data['data'])
            files = {'document': (file_data['name'], file_bytes)}
            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            r = requests.post(url, data={'chat_id': chat_id}, files=files, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            r = requests.post(url, json={'chat_id': chat_id, 'text': text}, timeout=10)
            
        result = r.json()
        
        if result.get('ok'):
            new_msg = {
                'text': text if text else f"📎 {file_data['name']}",
                'is_my': True,
                'time': datetime.now().isoformat(),
                'sender': 'You'
            }
            
            if bot_token not in user_data.get('bots', {}):
                user_data.setdefault('bots', {})[bot_token] = {"chats": {}, "history": {}}
            if chat_id not in user_data['bots'][bot_token]['history']:
                user_data['bots'][bot_token]['history'][chat_id] = []
                
            user_data['bots'][bot_token]['history'][chat_id].append(new_msg)
            UserManager.save_user_data(user_data)
            
            return jsonify({'success': True, 'message': new_msg})
        else:
            return jsonify({'error': result.get('description', 'Unknown error')}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings', methods=['POST'])
def get_settings():
    data = request.json
    token = data.get('token')
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify(user_data.get('settings', {}))

@app.route('/api/settings/update', methods=['POST'])
def update_settings():
    data = request.json
    token = data.get('token')
    settings = data.get('settings')
    
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_data = UserManager.get_user_by_token(token)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    
    user_data['settings'] = settings
    UserManager.save_user_data(user_data)
    return jsonify({'success': True})

@socketio.on('connect')
def handle_connect():
    print('Client connected')

def init_pollers_for_user(user_data):
    if user_data['id'] not in user_pollers:
        user_pollers[user_data['id']] = {}
    for bot_token in user_data.get('bots', {}):
        if bot_token not in user_pollers[user_data['id']]:
            poller = UserBotPoller(user_data['id'], bot_token, socketio)
            poller.start()
            user_pollers[user_data['id']][bot_token] = poller

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    
    # Загружаем существующих пользователей
    for filename in os.listdir(USERS_DIR):
        if filename.endswith('.json'):
            with open(os.path.join(USERS_DIR, filename), 'r') as f:
                user_data = json.load(f)
                init_pollers_for_user(user_data)
    
    print(f"\n🚀 Запуск сервера на порту {port}")
    print(f"📱 Откройте в браузере: http://localhost:{port}\n")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
