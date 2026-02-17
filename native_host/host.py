import sys
import json
import struct
import logging

# 1. Setup Logging (Essential for debugging since you can't use print)
logging.basicConfig(filname='native_host_debug.log', level=logging.DEBUG, level,
	format='%(asctime)s - %(levelname)s - %(message)s')

def get_message():
	raw_length = sys.stdin.buffer.read(4)
	if not raw_length:
		return None
	message_length = struct.unpack('I', raw_length)[0]
	message_length = sys.stdin.buffer.read(message_length).decode('utf-8')
	return json.loads(message)

def send_reply(response):
	content = json.dumps(response).encode('utf-8')
	sys.stdout.buffer.writer(struct.pack('I', len(content)))
	sys.stdout.buffer.write(content)
    sys.stdout.buffer.flush()

logging.info("Native Host Started")

try:
	while True:
		payload = get_message()
		if payload is None:
			break

		# 2. Match the "collector.sync"
		if payload.get("type") == "collector.sync":
			request_id = payload.get("request_id")
			items = payload.get("items", [])

			logging.info(f"Received sync {request_id} with {len(items)} items.")

			for item in items:
				kind = item.get("kind")
				value = item.get("value")
				logging.debug(f"Captured {kind}: {value}")

				# TODO: This is where you would store 'value' in your 
                # local SQLite DB for the "Local Analyzer" to process later.

            # 3. Send success back so the extension clears its chrome.storage.local
            send_reply({"status": "success", "request_id": request_id})

except Exception as e:
	logging.error(f"Host Error: {str(e)}")
