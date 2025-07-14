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

# Configuration files
CONFIG_FILE = 'config.json'
SESSION_FILE = 'anon.session'
SENT_IDS_FILE = 'sent_ids.txt'
ERRORS_FILE = 'errors.txt'

def load_config():
    """Load configuration from file or return None if doesn't exist"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

async def get_input(prompt, is_phone=False, is_password=False, default=None):
    """Get user input with validation"""
    if is_password:
        import getpass
        return getpass.getpass(prompt)
    
    if is_phone:
        while True:
            phone = input(prompt)
            if phone.startswith('+') and phone[1:].isdigit():
                return phone
            print("Please enter in international format (+1234567890)")
    return input(prompt)

async def setup_config():
    """Get configuration either from file or user input"""
    config = load_config()
    
    if config and all(k in config for k in ['api_id', 'api_hash', 'phone_number']):
        print("\nLoaded existing configuration:")
        print(f"API ID: {config['api_id']}")
        print(f"Phone: {config['phone_number'][:3]}*****{config['phone_number'][-2:]}")
        
        use_existing = input("\nUse existing credentials? (Y/n): ").strip().lower()
        if use_existing in ('', 'y', 'yes'):
            config['source_channel'] = await get_input("Enter source channel name: ")
            config['target_channel'] = await get_input("Enter target channel name: ")
            return config
    
    print("\nTelegram Channel Copier - Initial Setup\n")
    config = {
        'api_id': await get_input("Enter your API ID: "),
        'api_hash': await get_input("Enter your API Hash: "),
        'phone_number': await get_input("Enter phone number (+1234567890): ", is_phone=True),
        'source_channel': await get_input("Enter source channel name: "),
        'target_channel': await get_input("Enter target channel name: ")
    }
    save_config(config)
    return config

def load_sent_ids():
    """Load already sent message IDs"""
    if not os.path.exists(SENT_IDS_FILE):
        return set()
    with open(SENT_IDS_FILE, 'r') as f:
        return set(int(line.strip()) for line in f if line.strip())

def save_sent_id(message_id):
    """Save a sent message ID"""
    with open(SENT_IDS_FILE, 'a') as f:
        f.write(f"{message_id}\n")

def log_error(error):
    """Log an error to the error file"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(ERRORS_FILE, 'a') as f:
        f.write(f"[{timestamp}] {error}\n")

async def get_entity_by_name(client, name):
    """Get entity by its name (for channels without username)"""
    async for dialog in client.iter_dialogs():
        if dialog.name == name:
            return dialog.entity
    raise ValueError(f"Channel '{name}' not found")

async def copy_message(client, source_entity, target_entity, message, progress_bar=None):
    """Copy a message from source to target channel"""
    try:
        # Skip if message is empty
        if not message.message and not message.media:
            return False
            
        # Handle media messages
        if message.media:
            # Download media file
            media_path = await client.download_media(message.media, file=bytes)
            
            # Combine caption and text
            caption = ""
            if message.media.caption:
                caption = message.media.caption
            if message.message:
                caption = f"{caption}\n\n{message.message}" if caption else message.message
            
            # Determine media type and send appropriately
            if isinstance(message.media, MessageMediaPhoto):
                sent_msg = await client.send_file(
                    target_entity,
                    media_path,
                    caption=caption.strip() or None,
                    parse_mode='html'
                )
            elif isinstance(message.media, (MessageMediaDocument, MessageMediaWebPage)):
                # Get file attributes if available
                attributes = None
                if hasattr(message.media, 'document') and message.media.document:
                    attributes = message.media.document.attributes
                
                sent_msg = await client.send_file(
                    target_entity,
                    media_path,
                    caption=caption.strip() or None,
                    parse_mode='html',
                    attributes=attributes,
                    force_document=isinstance(message.media, MessageMediaDocument)
                )
            
            # Clean up
            if isinstance(media_path, str) and os.path.exists(media_path):
                os.remove(media_path)
        
        # Handle text-only messages
        else:
            sent_msg = await client.send_message(
                target_entity,
                message.message,
                parse_mode='html'
            )
        
        # Handle pinned messages
        if message.pinned:
            await client.pin_message(target_entity, sent_msg)
        
        # Save the sent message ID
        save_sent_id(message.id)
        
        if progress_bar:
            progress_bar.update(1)
            
        return True
    
    except Exception as e:
        log_error(f"Error copying message {message.id}: {str(e)}")
        return False

async def main():
    """Main function to run the script"""
    config = await setup_config()
    
    client = TelegramClient(SESSION_FILE, int(config['api_id']), config['api_hash'])
    
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
