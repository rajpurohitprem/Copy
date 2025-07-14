import os
import json
import asyncio
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.tl.types import MessageService
from tqdm import tqdm

CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"
SKIPPED_MEDIA_LOG = "skipped_media.txt"

MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.jpg', '.jpeg', '.png', '.webp', '.mp3')

# Load config or ask user
def load_config():
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

    def prompt(key, prompt_text):
        if key not in config or not config[key]:
            config[key] = input(prompt_text)
        return config[key]

    prompt("api_id", "API ID: ")
    prompt("api_hash", "API Hash: ")
    prompt("phone", "Phone number (with +91...): ")
    prompt("source_channel", "Source Channel Name: ")
    prompt("target_channel", "Target Channel Name: ")

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    return config

# Load sent message IDs
def load_sent_ids():
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, "r") as f:
            return set(f.read().splitlines())
    return set()

# Append new sent message ID
def save_sent_id(msg_id):
    with open(SENT_LOG, "a") as f:
        f.write(str(msg_id) + "\n")

# Log errors
def log_error(text):
    with open(ERROR_LOG, "a") as f:
        f.write(text + "\n")

# Log skipped media
def log_skipped_media(msg_id, media_type, reason):
    with open(SKIPPED_MEDIA_LOG, "a") as f:
        f.write(f"{msg_id} - {media_type} - {reason}\n")

# Main logic
async def clone_messages():
    config = load_config()

    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    await client.start(phone=config["phone"])

    dialogs = await client.get_dialogs()

    src_entity = next((d.entity for d in dialogs if d.name == config["source_channel"]), None)
    tgt_entity = next((d.entity for d in dialogs if d.name == config["target_channel"]), None)

    if not src_entity or not tgt_entity:
        print("❌ Channel not found. Check config names.")
        return

    history = await client(GetHistoryRequest(
        peer=src_entity,
        limit=0,
        offset_date=None,
        offset_id=0,
        max_id=0,
        min_id=0,
        add_offset=0,
        hash=0
    ))
    total = history.count
    print(f"📦 Total messages to check: {total}")

    messages = await client.get_messages(src_entity, limit=total)
    sent_ids = load_sent_ids()

    for msg in tqdm(reversed(messages), desc="Copying messages"):
        if str(msg.id) in sent_ids:
            continue
        if isinstance(msg, MessageService):
            continue

        try:
            # Handle media
            if msg.media:
                try:
                    print(f"📥 Downloading media from msg {msg.id}...")
                    file_path = await msg.download_media()
                    if file_path:
                        await client.send_file(
                            tgt_entity,
                            file_path,
                            caption=msg.text or msg.message
                        )
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        print(f"✅ Sent media msg {msg.id}")
                    else:
                        reason = "download_media() returned None"
                        log_skipped_media(msg.id, str(type(msg.media)), reason)
                        print(f"⚠️ Skipped media msg {msg.id} — {reason}")
                except Exception as e:
                    log_error(f"Media Error [{msg.id}]: {e}")
                    log_skipped_media(msg.id, str(type(msg.media)), f"EXCEPTION: {e}")
                    print(f"❌ Error sending media msg {msg.id}: {e}")
            else:
                # Send plain text
                await client.send_message(tgt_entity, msg.text or msg.message)
                print(f"✉️ Sent text msg {msg.id}")

            # Handle pinning
            if msg.pinned:
                try:
                    last = (await client.get_messages(tgt_entity, limit=1))[0]
                    await client(UpdatePinnedMessageRequest(peer=tgt_entity, id=last.id, silent=True))
                    print(f"📌 Pinned message {last.id}")
                except Exception as e:
                    log_error(f"Pin Error [{msg.id}]: {e}")

            save_sent_id(msg.id)

        except Exception as e:
            log_error(f"General Error [{msg.id}]: {e}")
            print(f"❌ General error on msg {msg.id}: {e}")

    await client.disconnect()
    print("✅ Done.")

if __name__ == "__main__":
    asyncio.run(clone_messages())
