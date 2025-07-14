import os
import json
import shutil
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

def load_sent_ids():
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, "r") as f:
            return set(f.read().splitlines())
    return set()

def save_sent_id(msg_id):
    with open(SENT_LOG, "a") as f:
        f.write(str(msg_id) + "\n")

def log_error(text):
    with open(ERROR_LOG, "a") as f:
        f.write(text + "\n")

def log_skipped_media(msg_id, media_type, reason):
    with open(SKIPPED_MEDIA_LOG, "a") as f:
        f.write(f"{msg_id} - {media_type} - {reason}\n")

async def get_channel_selection(client, prompt_label):
    dialogs = await client.get_dialogs()
    channels = [d for d in dialogs if d.is_channel]

    print(f"\n🔽 Select {prompt_label}:")
    for idx, ch in enumerate(channels):
        print(f"[{idx}] {ch.name}")

    while True:
        try:
            choice = int(input(f"Enter number [0 - {len(channels) - 1}]: "))
            if 0 <= choice < len(channels):
                return channels[choice].entity
        except:
            pass
        print("❌ Invalid input. Try again.")

async def update_config_interactively():
    api_id = int(input("API ID: "))
    api_hash = input("API Hash: ")
    phone = input("Phone number (with +91...): ")

    client = TelegramClient(SESSION_FILE, api_id, api_hash)
    await client.connect()

    source = await get_channel_selection(client, "Source Channel")
    target = await get_channel_selection(client, "Target Channel")

    config = {
        "api_id": api_id,
        "api_hash": api_hash,
        "phone": phone,
        "source_id": source.id,
        "target_id": target.id
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    await client.disconnect()
    return config

async def load_or_prompt_config():
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

    change = input("🔧 Do you want to change config? (y/n): ").strip().lower()

    if not config or change == "y":
        config = await update_config_interactively()

    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    return config, client

async def clone_messages():
    config, client = await load_or_prompt_config()
    await client.start(phone=config["phone"])

    src_entity = await client.get_entity(config["source_id"])
    tgt_entity = await client.get_entity(config["target_id"])

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
        if str(msg.id) in sent_ids or isinstance(msg, MessageService):
            continue

        try:
            if msg.media:
                try:
                    file_path = await msg.download_media()
                    if file_path:
                        await client.send_file(
                            tgt_entity,
                            file_path,
                            caption=msg.text or msg.message
                        )
                        print(f"✅ Sent media msg {msg.id}")

                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                            elif os.path.isdir(file_path):
                                shutil.rmtree(file_path)
                            print(f"🗑️ Deleted {file_path}")
                        except Exception as e:
                            log_error(f"Cleanup Error [{msg.id}]: {e}")
                    else:
                        log_skipped_media(msg.id, str(type(msg.media)), "download_media() returned None")
                except Exception as e:
                    log_error(f"Media Error [{msg.id}]: {e}")
                    log_skipped_media(msg.id, str(type(msg.media)), f"EXCEPTION: {e}")
            else:
                text_content = msg.text or msg.message
                if text_content:
                    await client.send_message(tgt_entity, text_content)
                    print(f"✉️ Sent text msg {msg.id}")
                else:
                    log_skipped_media(msg.id, "text", "Empty message body")

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
