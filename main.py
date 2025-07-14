from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.tl.types import Message
from tqdm import tqdm
import os
import json
import asyncio

CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"

# Supported media types for cleanup
MEDIA_EXTENSIONS = ['.jpg', '.png', '.mp4', '.mp3', '.mkv', '.webp', '.pdf', '.docx', '.zip']

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    else:
        return setup_config()

def setup_config():
    config = {}
    config["api_id"] = int(input("API ID: "))
    config["api_hash"] = input("API Hash: ")
    config["phone"] = input("Phone number (with country code): ")
    config["source_channel"] = input("Source Channel username or ID: ")
    config["target_channel"] = input("Target Channel username or ID: ")
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    return config

def edit_config():
    config = load_config()
    print("Edit config (press Enter to keep current value):")
    for key in ["source_channel", "target_channel"]:
        new_val = input(f"{key} [{config[key]}]: ")
        if new_val.strip():
            config[key] = new_val
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    print("Config updated.")

def load_sent_ids():
    if not os.path.exists(SENT_LOG):
        return set()
    with open(SENT_LOG, "r") as f:
        return set(map(int, f.read().splitlines()))

def save_sent_id(msg_id):
    with open(SENT_LOG, "a") as f:
        f.write(f"{msg_id}\n")

def log_error(error):
    with open(ERROR_LOG, "a") as f:
        f.write(f"{str(error)}\n")

async def main():
    config = load_config()
    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    await client.start(phone=config["phone"])

    source = config["source_channel"]
    target = config["target_channel"]

    sent_ids = load_sent_ids()
    messages = []

    
except ValueError:
    print(f"❌ Cannot resolve '{source}'. Please make sure it's a valid channel username or ID.")
    return
        history = await client(GetHistoryRequest(
            peer=entity,
            limit=0,
            offset_date=None,
            offset_id=0,
            max_id=0,
            min_id=0,
            add_offset=0,
            hash=0
        ))
        total = history.count

        print(f"Total messages in source: {total}")

        offset_id = 0
        batch_size = 100

        pbar = tqdm(total=total, desc="Copying Messages")
        while True:
            history = await client(GetHistoryRequest(
                peer=entity,
                limit=batch_size,
                offset_id=offset_id,
                offset_date=None,
                add_offset=0,
                max_id=0,
                min_id=0,
                hash=0
            ))

            if not history.messages:
                break

            for msg in reversed(history.messages):
                offset_id = msg.id
                if msg.id in sent_ids:
                    continue

                try:
                    file = None
                    if msg.media:
                        file = await client.download_media(msg)
                    
                    sent = await client.send_message(
                        entity=target,
                        message=msg.message or '',
                        file=file if os.path.exists(file) else None,
                        link_preview=False
                    )

                    if msg.pinned:
                        await client(UpdatePinnedMessageRequest(
                            peer=target,
                            id=sent.id,
                            silent=True
                        ))

                    save_sent_id(msg.id)

                    # Delete media file after use
                    if file and os.path.exists(file):
                        os.remove(file)

                except Exception as e:
                    log_error(f"[{msg.id}] {str(e)}")
                pbar.update(1)

        pbar.close()
        print("Done.")

    finally:
        await client.disconnect()

if __name__ == "__main__":
    choice = input("Edit source/target channels? (y/n): ").strip().lower()
    if choice == 'y':
        edit_config()
    asyncio.run(main())
