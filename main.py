import os
import json
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.tl.types import MessageService, Message
from tqdm import tqdm
import asyncio

CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    else:
        return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def prompt_config():
    print("First-time setup or edit config.")
    api_id = int(input("API ID: "))
    api_hash = input("API Hash: ")
    phone = input("Phone (with country code): ")
    source_channel = input("Source Channel NAME (not username): ")
    target_channel = input("Target Channel NAME (not username): ")

    config = {
        "api_id": api_id,
        "api_hash": api_hash,
        "phone": phone,
        "source_channel": source_channel,
        "target_channel": target_channel
    }
    save_config(config)
    return config

def prompt_edit_channels(config):
    print("Current Channels:")
    print(f"Source: {config['source_channel']}")
    print(f"Target: {config['target_channel']}")
    if input("Edit source/target? (y/N): ").lower() == 'y':
        config['source_channel'] = input("New Source Channel NAME: ")
        config['target_channel'] = input("New Target Channel NAME: ")
        save_config(config)
    return config

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
        f.write(f"{error}\n")

async def main():
    config = load_config() or prompt_config()
    config = prompt_edit_channels(config)

    client = TelegramClient(SESSION_FILE, config['api_id'], config['api_hash'])
    await client.start(phone=config['phone'])

    try:
        source = await client.get_entity(config['source_channel'])
        target = await client.get_entity(config['target_channel'])
    except Exception as e:
        log_error(f"Failed to fetch entities: {e}")
        return

    sent_ids = load_sent_ids()
    all_messages = []
    offset_id = 0
    limit = 100

    print("Fetching messages...")
    while True:
        history = await client(GetHistoryRequest(
            peer=source,
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
        messages = history.messages
        all_messages.extend(messages)
        offset_id = messages[-1].id

    new_messages = [msg for msg in all_messages if msg.id not in sent_ids and isinstance(msg, Message)]

    print(f"Found {len(new_messages)} new messages.")
    for msg in tqdm(reversed(new_messages), desc="Copying"):
        try:
            if msg.media:
                file_path = await client.download_media(msg.media)
                sent_msg = await client.send_file(
                    target,
                    file_path,
                    caption=msg.message or None,
                    parse_mode='html'
                )
                os.remove(file_path)
            else:
                sent_msg = await client.send_message(
                    target,
                    msg.message or '',
                    parse_mode='html'
                )

            if msg.pinned:
                await client(UpdatePinnedMessageRequest(
                    peer=target,
                    id=sent_msg.id,
                    silent=True
                ))

            save_sent_id(msg.id)

        except Exception as e:
            log_error(f"Error on msg {msg.id}: {e}")

    await client.disconnect()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
