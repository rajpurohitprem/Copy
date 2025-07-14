import os
import json
from datetime import datetime
from tqdm import tqdm
from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaPhoto, 
    MessageMediaDocument,
    MessageMediaWebPage
)
from telethon.utils import get_extension

# Configuration files
CONFIG_FILE = 'config.json'
SESSION_FILE = 'anon.session'
SENT_IDS_FILE = 'sent_ids.txt'
ERRORS_FILE = 'errors.txt'
MAX_FILE_SIZE = 1.5 * 1024 * 1024 * 1024  # 1.5GB in bytes

class UploadProgressBar:
    def __init__(self, message, filename):
        self.message = message
        self.filename = filename
        self.pbar = None

    async def callback(self, current, total):
        if self.pbar is None:
            self.pbar = tqdm(
                desc=f"Uploading {self.filename}",
                total=total,
                unit='B',
                unit_scale=True,
                unit_divisor=1024
            )
        self.pbar.update(current - self.pbar.n)

def load_or_create_config():
    """Load existing config or create new one with user input"""
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    
    required_fields = {
        'api_id': ("Enter your API ID: ", False),
        'api_hash': ("Enter your API Hash: ", False),
        'phone_number': ("Enter phone number (+1234567890): ", True),
        'source_channel': ("Enter source channel name: ", False),
        'target_channel': ("Enter target channel name: ", False)
    }

    # Check for missing fields
    missing_fields = [field for field in required_fields if field not in config or not config[field]]
    
    if missing_fields:
        print("\nTelegram Channel Copier - Configuration")
        print("Please provide the following information:\n")
        
        for field in missing_fields:
            prompt, is_phone = required_fields[field]
            while True:
                value = input(prompt).strip()
                if is_phone:
                    if value.startswith('+') and value[1:].isdigit():
                        config[field] = value
                        break
                    print("Please enter in international format (+1234567890)")
                else:
                    if value:
                        config[field] = value
                        break
                    print("This field cannot be empty")
        
        # Save the complete config
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    
    return config

async def copy_large_media(client, target_entity, media, caption):
    """Handle large media files with progress tracking"""
    filename = f"temp_{datetime.now().timestamp()}"
    if hasattr(media, 'document'):
        ext = get_extension(media.document)
        filename += ext if ext else ''
    
    # Download with progress
    download_pbar = tqdm(
        desc=f"Downloading {filename}",
        unit='B',
        unit_scale=True,
        unit_divisor=1024
    )
    
    def download_progress(current, total):
        download_pbar.total = total
        download_pbar.update(current - download_pbar.n)
    
    media_path = await client.download_media(
        media,
        file=f"{filename}",
        progress_callback=download_progress
    )
    download_pbar.close()
    
    if not media_path:
        raise ValueError("Failed to download media")
    
    # Check file size
    file_size = os.path.getsize(media_path)
    if file_size > MAX_FILE_SIZE:
        os.remove(media_path)
        raise ValueError(f"File too large ({file_size/1024/1024:.2f}MB > {MAX_FILE_SIZE/1024/1024:.2f}MB)")
    
    # Upload with progress
    upload_progress = UploadProgressBar(None, os.path.basename(media_path))
    
    try:
        if isinstance(media, MessageMediaPhoto):
            sent_msg = await client.send_file(
                target_entity,
                media_path,
                caption=caption.strip() or None,
                parse_mode='html',
                progress_callback=upload_progress.callback,
                force_document=False
            )
        else:
            sent_msg = await client.send_file(
                target_entity,
                media_path,
                caption=caption.strip() or None,
                parse_mode='html',
                progress_callback=upload_progress.callback,
                force_document=True,
                attributes=getattr(media.document, 'attributes', None)
            )
        
        return sent_msg
    finally:
        if upload_progress.pbar:
            upload_progress.pbar.close()
        if os.path.exists(media_path):
            os.remove(media_path)

async def copy_message(client, source_entity, target_entity, message, progress_bar=None):
    """Copy a message from source to target channel"""
    try:
        if not message.message and not message.media:
            return False
            
        if message.media:
            # Combine caption and text
            caption = ""
            if message.media.caption:
                caption = message.media.caption
            if message.message:
                caption = f"{caption}\n\n{message.message}" if caption else message.message
            
            # Handle large files differently
            if hasattr(message.media, 'document') and message.media.document:
                file_size = message.media.document.size
                if file_size > 100 * 1024 * 1024:  # 100MB threshold
                    sent_msg = await copy_large_media(
                        client,
                        target_entity,
                        message.media,
                        caption
                    )
                else:
                    media_path = await client.download_media(message.media, file=bytes)
                    sent_msg = await client.send_file(
                        target_entity,
                        media_path,
                        caption=caption.strip() or None,
                        parse_mode='html',
                        attributes=message.media.document.attributes,
                        force_document=True
                    )
            else:
                media_path = await client.download_media(message.media, file=bytes)
                sent_msg = await client.send_file(
                    target_entity,
                    media_path,
                    caption=caption.strip() or None,
                    parse_mode='html',
                    force_document=False
                )
            
            if isinstance(media_path, str) and os.path.exists(media_path):
                os.remove(media_path)
        else:
            sent_msg = await client.send_message(
                target_entity,
                message.message,
                parse_mode='html'
            )
        
        if message.pinned:
            await client.pin_message(target_entity, sent_msg)
        
        save_sent_id(message.id)
        
        if progress_bar:
            progress_bar.update(1)
            
        return True
    
    except Exception as e:
        log_error(f"Error copying message {message.id}: {str(e)}")
        return False

async def main():
    """Main function to run the script"""
    config = load_or_create_config()
    
    client = TelegramClient(
        SESSION_FILE,
        int(config['api_id']),
        config['api_hash'],
        connection_retries=5,
        timeout=3600
    )
    
    try:
        await client.start(phone=config['phone_number'])
    except Exception as e:
        print(f"Failed to connect: {str(e)}")
        return
    
    try:
        source_entity = await get_entity_by_name(client, config['source_channel'])
        target_entity = await get_entity_by_name(client, config['target_channel'])
    except Exception as e:
        print(str(e))
        return
    
    sent_ids = load_sent_ids()
    
    print(f"\nFetching messages from '{config['source_channel']}'...")
    messages = []
    async for message in client.iter_messages(source_entity):
        messages.append(message)
    
    new_messages = [msg for msg in messages if msg.id not in sent_ids]
    
    if not new_messages:
        print("No new messages to copy.")
        return
    
    print(f"Found {len(new_messages)} new messages to copy to '{config['target_channel']}'")
    
    with tqdm(total=len(new_messages), desc="Copying messages") as pbar:
        for message in reversed(new_messages):
            await copy_message(client, source_entity, target_entity, message, pbar)
    
    print("\nDone!")

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
