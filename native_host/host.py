import sys
import json
import struct
import logging
import sqlite3

# 1. Setup Logging
logging.basicConfig(filename='native_host_debug.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def init_db():
    """Initializes the local database to store captured domains."""
    conn = sqlite3.connect('local_benefits.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS web_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT,
            kind TEXT,
            value TEXT,
            seen_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_recent_history(limit=10):
    """Utility for the GUI team to fetch recent activity."""
    try:
        conn = sqlite3.connect('local_benefits.db')
        cursor = conn.cursor()
        cursor.execute('SELECT kind, value, seen_at FROM web_history ORDER BY id DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except sqlite3.OperationalError:
        return []

def get_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    message_length = struct.unpack('I', raw_length)[0]
    message = sys.stdin.buffer.read(message_length).decode('utf-8')
    return json.loads(message)

def send_reply(response):
    content = json.dumps(response).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('I', len(content)))
    sys.stdout.buffer.write(content)
    sys.stdout.buffer.flush()

# Initialize the 'vault' before starting the main loop
init_db()
logging.info("Native Host Started & Database Initialized")

try:
    while True:
        payload = get_message()
        if payload is None:
            break

        # 2. Match the "collector.sync" contract sent by Zilver
        if payload.get("type") == "collector.sync":
            request_id = payload.get("request_id")
            items = payload.get("items", [])
            
            conn = sqlite3.connect('local_benefits.db')
            cursor = conn.cursor()

            for item in items:
                kind = item.get("kind")
                value = item.get("value")
                seen_at = item.get("seen_at")
                
                cursor.execute('''
                    INSERT INTO web_history (request_id, kind, value, seen_at)
                    VALUES (?, ?, ?, ?)
                ''', (request_id, kind, value, seen_at))
                
                logging.debug(f"Saved to DB - {kind}: {value}")

            conn.commit()
            conn.close()
            
            # 3. Confirm success so extension clears its chrome.storage.local
            send_reply({"status": "success", "request_id": request_id})

except Exception as e:
    logging.error(f"Host Error: {str(e)}")