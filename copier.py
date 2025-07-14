import os
import json
import asyncio
import logging
import time
from tqdm import tqdm
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import MessageService

CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"

logging.getLogger("telethon.network.mtprotosender").setLevel(logging.ERROR)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_sent_id(msg_id):
    with open(SENT_LOG, "a") as f:
        f.write(f"{msg_id}\n")

def load_sent_ids():
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG) as f:
            return set(int(line.strip()) for line in f)
    return set()

def log_error(msg):
    with open(ERROR_LOG, "a") as f:
        f.write(msg + "\n")

def progress_bar_callback(total):
    bar = tqdm(total=total, unit='B', unit_scale=True)
    def callback(current, total):
        bar.total = total
        bar.n = current
        bar.refresh()
        if current == total:
            bar.close()
    return callback

async def select_channel(client, prompt):
    print(f"\n🔍 Fetching channels for: {prompt}")
    dialogs = await client.get_dialogs()
    channels = [d for d in dialogs if d.is_channel]
    for i, ch in enumerate(channels):
        print(f"{i+1}. {ch.name} [{ch.id}]")
    idx = int(input(f"Select {prompt} (1-{len(channels)}): ")) - 1
    return channels[idx].id

async def interactive_config():
    config = {}
    config["api_id"] = int(input("API ID: "))
    config["api_hash"] = input("API Hash: ")
    config["phone"] = input("Phone number (with +91...): ")

    async with TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"]) as client:
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(config["phone"])
            code = input("🔐 Enter the code you received: ")
            try:
                await client.sign_in(config["phone"], code)
            except SessionPasswordNeededError:
                password = input("💬 2FA password: ")
                await client.sign_in(password=password)

        config["source_channel"] = await select_channel(client, "Source Channel")
        config["target_channel"] = await select_channel(client, "Target Channel")

    save_config(config)
    return config

async def update_source_target(config):
    async with TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"]) as client:
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(config["phone"])
            code = input("🔐 Enter the code you received: ")
            await client.sign_in(config["phone"], code)

        config["source_channel"] = await select_channel(client, "Source Channel")
        config["target_channel"] = await select_channel(client, "Target Channel")
    save_config(config)
    return config

async def clone_messages():
    config = load_config()
    
    if input("⚙️ Do you want to change config? (y/n): ").lower() == "y":
        config = await interactive_config()
    elif input("🔁 Do you want to change source and target channel? (y/n): ").lower() == "y":
        config = await update_source_target(config)

    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    await client.start()
    sent_ids = load_sent_ids()

    src_entity = await client.get_entity(config["source_channel"])
    tgt_entity = await client.get_entity(config["target_channel"])

    offset_id = 0
    limit = 100
    total = 0

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

        messages = history.messages
        if not messages:
            break

        for msg in reversed(messages):
            try:
                offset_id = msg.id
                if msg.id in sent_ids or isinstance(msg, MessageService):
                    continue

                if msg.media:
                    file_path = await client.download_media(
                        msg,
                        progress_callback=progress_bar_callback(msg.media.document.size if hasattr(msg.media, 'document') else 100)
                    )
                    await client.send_file(
                        tgt_entity,
                        file_path,
                        caption=msg.text or "",
                        progress_callback=progress_bar_callback(os.path.getsize(file_path))
                    )
                    os.remove(file_path)
                else:
                    if msg.text:
                        await client.send_message(tgt_entity, msg.text)

                if msg.pinned:
                    await client(UpdatePinnedMessageRequest(
                        peer=tgt_entity,
                        id=msg.id,
                        silent=False
                    ))

                save_sent_id(msg.id)
                sent_ids.add(msg.id)
                total += 1
                time.sleep(1)  # Pause between messages
            except Exception as e:
                log_error(f"[{msg.id}] {str(e)}")

    print(f"✅ Done. {total} messages copied.")

if __name__ == "__main__":
    asyncio.run(clone_messages())
