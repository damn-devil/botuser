# app.py - с поддержкой сохранения тем
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
import requests
import json
import threading
import time
import os
import sys
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.config['SECRET_KEY'] = 'telegram-bot-secret-key-change-this'
socketio = SocketIO(app, cors_allowed_origins="*")

# Хранилище данных
bots_data = {}
active_bots = {}
user_settings = {}

CONFIG_FILE = "web_config.json"
THEMES_FILE = "themes.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"bots": {}, "settings": {}}

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_themes():
    """Загрузка сохраненных тем"""
    if os.path.exists(THEMES_FILE):
        with open(THEMES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return get_default_themes()

def save_themes(themes):
    with open(THEMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(themes, f, ensure_ascii=False, indent=4)

def get_default_themes():
    return {
        "dark": {
            "name": "Темная (стандартная)",
            "colors": {
                "sidebar": "#101010",
                "main_bg": "#1e1e1e",
                "chat_list": "#151515",
                "accent": "#007aff",
                "text": "#ffffff",
                "text_secondary": "#888888",
                "bubble_own": "#007aff",
                "bubble_other": "#2d2d2d",
                "hover": "#2a2a2a",
                "border": "#3a3a3a"
            },
            "bubble_radius": 20,
            "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            "font_size": 14
        },
        "light": {
            "name": "Светлая",
            "colors": {
                "sidebar": "#f0f0f0",
                "main_bg": "#ffffff",
                "chat_list": "#f5f5f5",
                "accent": "#007aff",
                "text": "#1a1a1a",
                "text_secondary": "#666666",
                "bubble_own": "#e3f2fd",
                "bubble_other": "#f0f0f0",
                "hover": "#e8e8e8",
                "border": "#e0e0e0"
            },
            "bubble_radius": 20,
            "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            "font_size": 14
        },
        "green": {
            "name": "Зеленая",
            "colors": {
                "sidebar": "#0a2f1f",
                "main_bg": "#0e3d2a",
                "chat_list": "#0c3522",
                "accent": "#2ecc71",
                "text": "#ffffff",
                "text_secondary": "#a8e6cf",
                "bubble_own": "#27ae60",
                "bubble_other": "#1e5631",
                "hover": "#1a4d2e",
                "border": "#2c5e41"
            },
            "bubble_radius": 24,
            "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            "font_size": 14
        },
        "purple": {
            "name": "Фиолетовая",
            "colors": {
                "sidebar": "#1a0b2e",
                "main_bg": "#24123a",
                "chat_list": "#1e0f33",
                "accent": "#9b59b6",
                "text": "#ffffff",
                "text_secondary": "#d4a5ff",
                "bubble_own": "#8e44ad",
                "bubble_other": "#2d1b47",
                "hover": "#2a1742",
                "border": "#3d2a5c"
            },
            "bubble_radius": 16,
            "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            "font_size": 14
        },
        "ocean": {
            "name": "Океан",
            "colors": {
                "sidebar": "#001f3f",
                "main_bg": "#003366",
                "chat_list": "#002a4f",
                "accent": "#00b4d8",
                "text": "#ffffff",
                "text_secondary": "#90e0ef",
                "bubble_own": "#0077b6",
                "bubble_other": "#023e8a",
                "hover": "#004c80",
                "border": "#0077b6"
            },
            "bubble_radius": 20,
            "font_family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            "font_size": 14
        }
    }

data = load_config()
bots_data = data["bots"]
user_settings = data.get("settings", {"current_theme": "dark"})
available_themes = load_themes()

class BotUpdatePoller:
    def __init__(self, token, socketio_instance):
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
                params = {"offset": offset, "timeout": 5}
                r = requests.get(url, params=params, timeout=10)
                result = r.json()
                
                if result.get("ok") and result["result"]:
                    for update in result["result"]:
                        self.process_update(update)
                        self.last_update_id = update["update_id"]
            except Exception as e:
                print(f"Polling error for {self.token}: {e}")
            time.sleep(0.5)
            
    def process_update(self, update):
        message = update.get("message")
        if not message:
            return
            
        chat_id = str(message["chat"]["id"])
        chat_name = message["chat"].get("title") or message["from"].get("first_name", "Unknown")
        text = message.get("text", "📎 Вложение")
        
        if self.token not in bots_data:
            bots_data[self.token] = {"chats": {}, "history": {}}
        
        if chat_id not in bots_data[self.token]["chats"]:
            bots_data[self.token]["chats"][chat_id] = {"name": chat_name, "unread": 0}
            bots_data[self.token]["history"][chat_id] = []
            
        new_msg = {
            "text": text,
            "is_my": False,
            "time": datetime.now().isoformat(),
            "sender": chat_name
        }
        bots_data[self.token]["history"][chat_id].append(new_msg)
        bots_data[self.token]["chats"][chat_id]["unread"] += 1
        
        save_config({"bots": bots_data, "settings": user_settings})
        
        self.socketio.emit('new_message', {
            'token': self.token,
            'chat_id': chat_id,
            'message': new_msg
        })
        
    def stop(self):
        self.running = False

@app.route('/offline')
def offline():
    return render_template('offline.html')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/themes', methods=['GET'])
def get_themes():
    return jsonify({
        "available": available_themes,
        "current": user_settings.get("current_theme", "dark")
    })

@app.route('/api/themes/<theme_id>', methods=['POST'])
def apply_theme(theme_id):
    if theme_id in available_themes:
        user_settings["current_theme"] = theme_id
        save_config({"bots": bots_data, "settings": user_settings})
        return jsonify({"success": True, "theme": available_themes[theme_id]})
    return jsonify({"error": "Theme not found"}), 404

@app.route('/api/themes/custom', methods=['POST'])
def save_custom_theme():
    theme_data = request.json
    theme_id = theme_data.get("id")
    theme_name = theme_data.get("name")
    theme_config = theme_data.get("config")
    
    if theme_id and theme_config:
        available_themes[theme_id] = {
            "name": theme_name,
            "colors": theme_config.get("colors", {}),
            "bubble_radius": theme_config.get("bubble_radius", 20),
            "font_family": theme_config.get("font_family", "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"),
            "font_size": theme_config.get("font_size", 14)
        }
        save_themes(available_themes)
        return jsonify({"success": True})
    return jsonify({"error": "Invalid theme data"}), 400

@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(user_settings)

@app.route('/api/bots', methods=['GET'])
def get_bots():
    bot_list = []
    for token, info in bots_data.items():
        bot_list.append({
            'token': token,
            'username': info.get('username', 'Unknown'),
            'chats_count': len(info.get('chats', {})),
            'unread_total': sum(c.get('unread', 0) for c in info.get('chats', {}).values())
        })
    return jsonify(bot_list)

@app.route('/api/bots', methods=['POST'])
def add_bot():
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'Token is required'}), 400
        
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        result = r.json()
        
        if result.get("ok"):
            username = result["result"]["username"]
            
            if token not in bots_data:
                bots_data[token] = {
                    "username": username,
                    "chats": {},
                    "history": {}
                }
                
            save_config({"bots": bots_data, "settings": user_settings})
            
            poller = BotUpdatePoller(token, socketio)
            poller.start()
            active_bots[token] = poller
            
            return jsonify({'success': True, 'username': username})
        else:
            return jsonify({'error': 'Invalid token'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bots/<token>', methods=['DELETE'])
def remove_bot(token):
    if token in bots_data:
        if token in active_bots:
            active_bots[token].stop()
            del active_bots[token]
        del bots_data[token]
        save_config({"bots": bots_data, "settings": user_settings})
        return jsonify({'success': True})
    return jsonify({'error': 'Bot not found'}), 404

@app.route('/api/bots/<token>/activate', methods=['POST'])
def activate_bot(token):
    if token in bots_data:
        session['active_token'] = token
        return jsonify({'success': True})
    return jsonify({'error': 'Bot not found'}), 404

@app.route('/api/bots/active', methods=['GET'])
def get_active_bot():
    token = session.get('active_token')
    if token and token in bots_data:
        return jsonify({'token': token, 'username': bots_data[token]['username']})
    return jsonify({'token': None})

@app.route('/api/chats/<token>', methods=['GET'])
def get_chats(token):
    if token in bots_data:
        chats = list(bots_data[token].get('chats', {}).items())
        chat_list = [{'id': cid, 'name': info['name'], 'unread': info.get('unread', 0)} 
                     for cid, info in chats]
        return jsonify(chat_list)
    return jsonify([])

@app.route('/api/messages/<token>/<chat_id>', methods=['GET'])
def get_messages(token, chat_id):
    if token in bots_data:
        history = bots_data[token].get('history', {}).get(chat_id, [])
        if chat_id in bots_data[token].get('chats', {}):
            bots_data[token]['chats'][chat_id]['unread'] = 0
            save_config({"bots": bots_data, "settings": user_settings})
        return jsonify(history)
    return jsonify([])

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    token = data.get('token')
    chat_id = data.get('chat_id')
    text = data.get('text', '').strip()
    file_data = data.get('file')
    
    if not token or not chat_id or (not text and not file_data):
        return jsonify({'error': 'Missing parameters'}), 400
        
    try:
        if file_data:
            import base64
            file_bytes = base64.b64decode(file_data['data'])
            files = {'document': (file_data['name'], file_bytes)}
            url = f"https://api.telegram.org/bot{token}/sendDocument"
            r = requests.post(url, data={'chat_id': chat_id}, files=files, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            r = requests.post(url, json={'chat_id': chat_id, 'text': text}, timeout=10)
            
        result = r.json()
        
        if result.get('ok'):
            new_msg = {
                'text': text if text else f"📎 {file_data['name']}",
                'is_my': True,
                'time': datetime.now().isoformat(),
                'sender': 'You'
            }
            
            if token not in bots_data:
                bots_data[token] = {"chats": {}, "history": {}}
            if chat_id not in bots_data[token]['history']:
                bots_data[token]['history'][chat_id] = []
                
            bots_data[token]['history'][chat_id].append(new_msg)
            save_config({"bots": bots_data, "settings": user_settings})
            
            return jsonify({'success': True, 'message': new_msg})
        else:
            return jsonify({'error': result.get('description', 'Unknown error')}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/chats/<token>/<chat_id>/mark_read', methods=['POST'])
def mark_chat_read(token, chat_id):
    if token in bots_data and chat_id in bots_data[token].get('chats', {}):
        bots_data[token]['chats'][chat_id]['unread'] = 0
        save_config({"bots": bots_data, "settings": user_settings})
        return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404

@socketio.on('connect')
def handle_connect():
    emit('connected', {'data': 'Connected'})

def init_pollers():
    for token in bots_data:
        poller = BotUpdatePoller(token, socketio)
        poller.start()
        active_bots[token] = poller

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    
    print(f"\n🚀 Запуск сервера на порту {port}")
    print(f"📱 Откройте в браузере: http://localhost:{port}")
    print(f"⚙️  Для остановки нажмите Ctrl+C\n")
    
    init_pollers()
    socketio.run(app, host='0.0.0.0', port=port, debug=True)