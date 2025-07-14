import os
import json
from datetime import datetime
from tqdm import tqdm
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage

# Configuration file
CONFIG_FILE = 'config.json'
SESSION_FILE = 'anon.session'
SENT_IDS_FILE = 'sent_ids.txt'
ERRORS_FILE = 'errors.txt'

# Default config template
DEFAULT_CONFIG = {
    'api_id': '',
    'api_hash': '',
    'phone_number': '',
    'source_channel_name': '',
    'target_channel_name': ''
}

def load_config():
    """Load or create configuration file"""
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        print(f"Created {CONFIG_FILE}. Please fill in your details.")
        exit()
    
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    
    # Validate config
    required_fields = ['api_id', 'api_hash', 'phone_number', 'source_channel_name', 'target_channel_name']
    for field in required_fields:
        if not config.get(field):
            print(f"Please fill in '{field}' in {CONFIG_FILE}")
            exit()
    
    return config

def edit_config():
    """Edit configuration interactively"""
    config = load_config()
    
    print("\nCurrent configuration:")
    for key, value in config.items():
        print(f"{key}: {value}")
    
    print("\nEdit configuration (leave blank to keep current value):")
    for key in config.keys():
        new_value = input(f"{key} [{config[key]}]: ").strip()
        if new_value:
            config[key] = new_value
    
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)
    
    print("Configuration updated successfully!")
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
        # Check if message has media
        if message.media:
            # Download media
            media_path = await client.download_media(message.media)
            
            # Prepare caption
            caption = message.text or message.message
            if message.media.caption:
                caption = message.media.caption + (f"\n\n{caption}" if caption else "")
            
            # Send based on media type
            if isinstance(message.media, MessageMediaPhoto):
                sent_msg = await client.send_file(
                    target_entity,
                    media_path,
                    caption=caption,
                    parse_mode='html'
                )
            elif isinstance(message.media, (MessageMediaDocument, MessageMediaWebPage)):
                sent_msg = await client.send_file(
                    target_entity,
                    media_path,
                    caption=caption,
                    parse_mode='html',
                    attributes=message.media.document.attributes if hasattr(message.media, 'document') else None
                )
            
            # Clean up downloaded file
            if media_path and os.path.exists(media_path):
                os.remove(media_path)
        else:
            # Send text message
            sent_msg = await client.send_message(
                target_entity,
                message.text or message.message,
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
    # Load configuration
    config = load_config()
    
    # Initialize client
    client = TelegramClient(SESSION_FILE, config['api_id'], config['api_hash'])
    
    # Connect to Telegram
    try:
        await client.start(phone=config['phone_number'])
    except Exception as e:
        print(f"Failed to connect: {str(e)}")
        return
    
    # Get source and target channels
    try:
        source_entity = await get_entity_by_name(client, config['source_channel_name'])
        target_entity = await get_entity_by_name(client, config['target_channel_name'])
    except Exception as e:
        print(str(e))
        return
    
    # Load already sent message IDs
    sent_ids = load_sent_ids()
    
    # Get all messages from source channel
    print(f"Fetching messages from '{config['source_channel_name']}'...")
    messages = []
    async for message in client.iter_messages(source_entity):
        messages.append(message)
    
    # Filter out already sent messages
    new_messages = [msg for msg in messages if msg.id not in sent_ids]
    
    if not new_messages:
        print("No new messages to copy.")
        return
    
    print(f"Found {len(new_messages)} new messages to copy to '{config['target_channel_name']}'")
    
    # Copy messages with progress bar
    with tqdm(total=len(new_messages), desc="Copying messages") as pbar:
        for message in reversed(new_messages):  # Copy in chronological order
            await copy_message(client, source_entity, target_entity, message, pbar)
    
    print("Done!")

if __name__ == '__main__':
    import asyncio
    
    # Check if user wants to edit config
    if input("Edit configuration before starting? (y/N): ").lower() == 'y':
        edit_config()
    
    # Run the main function
    asyncio.run(main())
