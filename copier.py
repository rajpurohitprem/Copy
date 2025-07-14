import os, re, json, asyncio, logging
from tqdm import tqdm
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest, UpdatePinnedMessageRequest
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import MessageService

# Paths & logging
CONFIG_FILE = "config.json"
SESSION_FILE = "anon"
SENT_LOG = "sent_ids.txt"
ERROR_LOG = "errors.txt"
logging.getLogger("telethon.network.mtprotosender").setLevel(logging.ERROR)

# Helpers
def load_cfg(): return json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else {}
def save_cfg(c): json.dump(c, open(CONFIG_FILE, "w"), indent=2)
def log_err(m): open(ERROR_LOG,"a").write(m+"\n")
def progress_cb(total):
    bar = tqdm(total=total, unit="B", unit_scale=True)
    def cb(cur, tot):
        bar.total = tot; bar.n = cur; bar.refresh()
        if cur >= tot: bar.close()
    return cb

def extract_id(link):
    m = re.search(r'/(\d+)(?:\?.*)?$', link)
    return int(m.group(1)) if m else None

async def select_ch(client, label):
    dialogs = await client.get_dialogs()
    options = [d for d in dialogs if d.is_channel or d.is_group]
    for i, d in enumerate(options, 1):
        print(f"{i}. {d.name}")
    idx = int(input(f"Select {label} number: ")) - 1
    return options[idx].name

async def setup_config():
    cfg = load_cfg()
    if input("🔧 Change full config? (y/n): ").lower()=="y" or not cfg.get("api_id"):
        cfg["api_id"]=int(input("API ID: "))
        cfg["api_hash"]=input("API Hash: ")
        cfg["phone"]=input("Phone (+...): ")

    async with TelegramClient(SESSION_FILE, cfg["api_id"], cfg["api_hash"]) as cli:
        if not await cli.is_user_authorized():
            await cli.send_code_request(cfg["phone"])
            code=input("🔐 Enter code: ")
            try: await cli.sign_in(cfg["phone"], code)
            except SessionPasswordNeededError:
                pwd=input("2FA password: ")
                await cli.sign_in(password=pwd)
        if input("🔁 Change channels? (y/n): ").lower()=="y" or not cfg.get("source_channel"):
            cfg["source_channel"] = await select_ch(cli, "Source Channel")
            cfg["target_channel"] = await select_ch(cli, "Target Channel")
    save_cfg(cfg)
    return cfg

async def clone():
    cfg = await setup_config()
    client = TelegramClient(SESSION_FILE, cfg["api_id"], cfg["api_hash"])
    await client.start()

    src = await client.get_entity(cfg["source_channel"])
    tgt = await client.get_entity(cfg["target_channel"])

    # Define range
    start_id = 0; end_id = None
    if input("📌 Custom range? (y/n): ").lower()=="y":
        s_link = input("🔹 Start message link: ").strip()
        start_id = extract_id(s_link) - 1
        e_link = input("🔹 End message link: ").strip()
        end_id = extract_id(e_link)

    total_copied = 0
    offset_id = start_id

    while True:
        hist = await client(GetHistoryRequest(
            peer=src, offset_id=offset_id, limit=100,
            max_id=0, min_id=0, add_offset=0, hash=0
        ))
        msgs = hist.messages
        if not msgs: break

        for msg in reversed(msgs):
            if msg.id <= start_id: continue
            if end_id is not None and msg.id > end_id: continue

            try:
                if msg.media:
                    path = await client.download_media(
                        msg, progress_callback=progress_cb(
                            getattr(msg.media, "document", msg.media).size if hasattr(msg.media, "document") else 0
                        )
                    )
                    await client.send_file(
                        tgt, path, caption=msg.text or "",
                        progress_callback=progress_cb(os.path.getsize(path))
                    )
                    os.remove(path)
                else:
                    text = msg.text or msg.message
                    if text:
                        await client.send_message(tgt, text)
                if msg.pinned:
                    last = (await client.get_messages(tgt, limit=1))[0]
                    await client(UpdatePinnedMessageRequest(peer=tgt, id=last.id, silent=False))
                offset_id = msg.id
                total_copied += 1
                await asyncio.sleep(1)
            except Exception as e:
                log_err(f"[{msg.id}] {e}")

        if len(msgs)<100 or (end_id is not None and offset_id>=end_id): break

    print(f"✅ Done! Copied {total_copied} messages.")

if __name__=="__main__":
    asyncio.run(clone())
