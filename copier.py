# Updated version with full tqdm progress bars:
# - Message cloning progress bar
# - Download progress bar (per media)
# - Upload progress bar (per media)
# - Works in Termux and standard terminals

import os
import json
import asyncio
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.tl.types import MessageService, Message
from tqdm import tqdm

CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"

# Ensure logs exist
open(SENT_LOG, "a").close()
open(ERROR_LOG, "a").close()

def load_json():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_json(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

async def get_channel_selection(client, prompt_text):
    dialogs = await client.get_dialogs()
    channels = [d for d in dialogs if d.is_channel and not d.is_user]
    print(f"\n📢 Available Channels/Groups for {prompt_text}:")
    for i, d in enumerate(channels, 1):
        print(f"{i}. {d.name}")
    choice = int(input(f"🟢 Enter number for {prompt_text}: "))
    return channels[choice - 1].entity

async def update_config_interactively(client):
    config = load_json()
    source = await get_channel_selection(client, "Source Channel")
    target = await get_channel_selection(client, "Target Channel")
    config["source_channel_id"] = source.id
    config["target_channel_id"] = target.id
    save_json(config)
    return config

async def load_or_prompt_config():
    config = load_json()
    if not all(k in config for k in ("api_id", "api_hash", "phone")):
        print("🔧 Enter your Telegram API config:")
        config["api_id"] = int(input("API ID: "))
        config["api_hash"] = input("API Hash: ")
        config["phone"] = input("Phone number (with +91...): ")
        save_json(config)

    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    await client.start(phone=config["phone"])

    change_all = input("🔧 Do you want to change config? (y/n): ").lower()
    if change_all == "y":
        print("👉 Full config edit selected.")
        config["api_id"] = int(input("API ID: "))
        config["api_hash"] = input("API Hash: ")
        config["phone"] = input("Phone number (with +91...): ")
        save_json(config)

    change_channels = input("🌀 Do you want to change source and target channels? (y/n): ").lower()
    if change_channels == "y":
        config = await update_config_interactively(client)

    return config, client

def log_error(msg):
    with open(ERROR_LOG, "a") as f:
        f.write(msg + "\n")

async def clone_messages():
    config, client = await load_or_prompt_config()

    src_entity = await client.get_entity(int(config["source_channel_id"]))
    tgt_entity = await client.get_entity(int(config["target_channel_id"]))

    with open(SENT_LOG, "r") as f:
        sent_ids = set(map(int, f.read().split()))

    offset_id = 0
    limit = 100
    all_messages = []

    print("📥 Fetching messages from source...")
    while True:
        history = await client(GetHistoryRequest(
            peer=src_entity,
            offset_id=offset_id,
            offset_date=None,
            add_offset=0,
            limit=limit,
            max_id=0,
            min_id=0,
            hash=0
        ))
        if not history.messages:
            break
        all_messages.extend(history.messages)
        offset_id = history.messages[-1].id

    all_messages.reverse()
    message_pbar = tqdm(total=len(all_messages), desc="Cloning messages")

    total_sent = 0

    for msg in all_messages:
        message_pbar.update(1)
        if not isinstance(msg, Message) or msg.id in sent_ids:
            continue

        try:
            if msg.media:
                file_size = {"value": 0}

                def download_callback(cur, total):
                    file_size["value"] = total
                    tqdm.write(f"📥 Downloading {cur/1024:.1f} KB / {total/1024:.1f} KB", end="\r")

                file_path = await client.download_media(msg, progress_callback=download_callback)
                upload_bar = tqdm(total=file_size["value"], unit='B', unit_scale=True, desc="📤 Uploading")

                def upload_callback(sent, total):
                    upload_bar.update(sent - upload_bar.n)

                await client.send_file(
                    tgt_entity,
                    file_path,
                    caption=msg.text or msg.message or "",
                    progress_callback=upload_callback
                )
                upload_bar.close()
                os.remove(file_path)

            elif msg.text or msg.message:
                await client.send_message(tgt_entity, msg.text or msg.message)

            if msg.pinned:
                try:
                    await client(UpdatePinnedMessageRequest(
                        peer=tgt_entity,
                        id=msg.id,
                        silent=True
                    ))
                except:
                    pass

            with open(SENT_LOG, "a") as f:
                f.write(f"{msg.id}\n")
            total_sent += 1
            await asyncio.sleep(1)

        except Exception as e:
            log_error(f"Message ID {msg.id} failed: {str(e)}")

    message_pbar.close()
    print(f"✅ Cloning complete. {total_sent} messages sent.")

if __name__ == "__main__":
    asyncio.run(clone_messages())
