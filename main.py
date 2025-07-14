from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.tl.types import MessageService
from telethon.errors import ChannelInvalidError
from tqdm import tqdm
import os, json, asyncio

CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"

MEDIA_TYPES = ('.jpg', '.jpeg', '.png', '.mp4', '.mkv', '.webp', '.mp3', '.pdf', '.docx')

# Ensure sent_ids.txt exists
if not os.path.exists(SENT_LOG):
    with open(SENT_LOG, 'w') as f: pass

def log_error(err_msg):
    with open(ERROR_LOG, "a") as f:
        f.write(err_msg + "\n")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    else:
        config = {}

    required_keys = ["api_id", "api_hash", "phone", "source_channel", "target_channel"]
    for key in required_keys:
        if key not in config or not config[key]:
            config[key] = input(f"Enter {key.replace('_', ' ')}: ").strip()

    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    return config

def edit_channels():
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    print(f"\nCurrent channels:\nSource: {config['source_channel']}\nTarget: {config['target_channel']}")
    if input("Edit them? (y/N): ").lower() == 'y':
        config['source_channel'] = input("New Source Channel Name: ").strip()
        config['target_channel'] = input("New Target Channel Name: ").strip()
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print("Updated.")

async def clone_messages():
    config = load_config()
    edit_channels()

    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    await client.start(phone=config["phone"])

    try:
        src_entity = await client.get_entity(config["source_channel"])
        tgt_entity = await client.get_entity(config["target_channel"])
    except ChannelInvalidError:
        log_error("Invalid source or target channel. Please double-check channel names.")
        return

    sent_ids = set(open(SENT_LOG).read().splitlines())

    history = await client(GetHistoryRequest(
        peer=src_entity, offset_id=0, offset_date=None,
        add_offset=0, limit=500, max_id=0, min_id=0, hash=0))

    messages = history.messages[::-1]  # oldest first
    progress = tqdm(messages, desc="Copying messages")

    for msg in progress:
        try:
            if str(msg.id) in sent_ids or isinstance(msg, MessageService):
                continue

            if msg.media:
                file = await msg.download_media()
                await client.send_file(tgt_entity, file, caption=msg.text or msg.message)
                if file and os.path.exists(file):
                    os.remove(file)
            else:
                await client.send_message(tgt_entity, msg.text or msg.message)

            if msg.pinned:
                await client(UpdatePinnedMessageRequest(
                    peer=tgt_entity, id=msg.id, silent=False))

            with open(SENT_LOG, 'a') as f:
                f.write(f"{msg.id}\n")

        except Exception as e:
            log_error(f"Error with message ID {msg.id}: {e}")

    print("✅ Done.")

if __name__ == "__main__":
    asyncio.run(clone_messages())
