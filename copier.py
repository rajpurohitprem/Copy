import os
import json
import asyncio
import time
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
    return set(open(SENT_LOG).read().splitlines()) if os.path.exists(SENT_LOG) else set()

def save_sent_id(msg_id):
    with open(SENT_LOG, "a") as f:
        f.write(str(msg_id) + "\n")

def log_error(text):
    with open(ERROR_LOG, "a") as f:
        f.write(text + "\n")

def log_skipped_media(msg_id, media_type, reason):
    with open(SKIPPED_MEDIA_LOG, "a") as f:
        f.write(f"{msg_id} - {media_type} - {reason}\n")

async def prompt_channel_selection(client, config):
    dialogs = await client.get_dialogs()
    channels = [d for d in dialogs if d.is_channel or d.is_group]

    print("\n📢 Available Channels/Groups:")
    for i, d in enumerate(channels):
        print(f"{i + 1}. {d.name}")

    src_idx = int(input("🟢 Enter number for Source Channel/Group: ")) - 1
    tgt_idx = int(input("🔵 Enter number for Target Channel/Group: ")) - 1

    config["source_channel"] = channels[src_idx].name
    config["target_channel"] = channels[tgt_idx].name

    return config

async def load_config():
    config = {}

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

    change_all = input("🔧 Do you want to change config? (y/n): ").lower().strip()

    if change_all == "y" or not config.get("api_id"):
        config["api_id"] = int(input("API ID: "))
        config["api_hash"] = input("API Hash: ")
        config["phone"] = input("Phone number (with +91...): ")

        client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
        await client.start(phone=config["phone"])
        config = await prompt_channel_selection(client, config)
        await client.disconnect()

    else:
        change_channels = input("🔁 Do you want to change source and target channels? (y/n): ").lower().strip()
        if change_channels == "y":
            client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
            await client.start(phone=config["phone"])
            config = await prompt_channel_selection(client, config)
            await client.disconnect()

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    return config

async def clone_messages():
    config = await load_config()

    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    await client.start(phone=config["phone"])

    dialogs = await client.get_dialogs()
    src_entity = next((d.entity for d in dialogs if d.name == config["source_channel"]), None)
    tgt_entity = next((d.entity for d in dialogs if d.name == config["target_channel"]), None)

    if not src_entity or not tgt_entity:
        print("❌ Source or target channel not found.")
        return

    messages = await client.get_messages(src_entity, limit=None)
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
                        os.remove(file_path)
                        print(f"✅ Sent media msg {msg.id}")
                    else:
                        log_skipped_media(msg.id, str(type(msg.media)), "download_media() returned None")
                except Exception as e:
                    log_error(f"Media Error [{msg.id}]: {e}")
                    log_skipped_media(msg.id, str(type(msg.media)), f"EXCEPTION: {e}")
            else:
                text = msg.text or msg.message
                if text:
                    await client.send_message(tgt_entity, text)
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
            await asyncio.sleep(1)  # 1 second delay

        except Exception as e:
            log_error(f"General Error [{msg.id}]: {e}")
            print(f"❌ Error on msg {msg.id}: {e}")

    await client.disconnect()
    print("✅ Done copying.")

if __name__ == "__main__":
    asyncio.run(clone_messages())
