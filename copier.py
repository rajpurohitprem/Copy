from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.tl.types import MessageService
from tqdm import tqdm
import os, json, asyncio

CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"

# ------------------------- Helpers -------------------------

def log_error(err_msg):
    with open(ERROR_LOG, "a") as f:
        f.write(err_msg + "\n")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    else:
        config = {}

    required_keys = ["api_id", "api_hash", "phone"]
    for key in required_keys:
        if key not in config or not config[key]:
            config[key] = input(f"Enter {key.replace('_', ' ')}: ").strip()

    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    return config

def edit_channels(client):
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)

    dialogs = client.get_dialogs()
    channels = [d for d in dialogs if d.is_channel]

    def choose_channel(prompt):
        print(f"\n{prompt}")
        for idx, ch in enumerate(channels):
            print(f"[{idx}] {ch.name}")
        choice = int(input("Enter number: "))
        return channels[choice].name

    if "source_channel" not in config or "target_channel" not in config or \
       input("Edit source/target channels? (y/N): ").lower() == 'y':
        config["source_channel"] = choose_channel("Select source channel")
        config["target_channel"] = choose_channel("Select target channel")

        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

    return config

# ----------------------- Main Logic ------------------------

async def clone_messages():
    config = load_config()
    client = TelegramClient(SESSION_FILE, config["api_id"], config["api_hash"])
    await client.start(phone=config["phone"])

    config = edit_channels(client)

    dialogs = await client.get_dialogs()
    src_entity = next((d.entity for d in dialogs if d.name == config["source_channel"]), None)
    tgt_entity = next((d.entity for d in dialogs if d.name == config["target_channel"]), None)

    if not src_entity or not tgt_entity:
        raise ValueError("❌ Source or target channel not found in your joined channels.")

    if not os.path.exists(SENT_LOG):
        open(SENT_LOG, "w").close()
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
            log_error(f"Error on message {msg.id}: {e}")

    print("✅ Done.")

# ------------------------- Entry ---------------------------

if __name__ == "__main__":
    asyncio.run(clone_messages())
