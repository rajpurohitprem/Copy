import os
import json
from datetime import datetime
from tqdm import tqdm
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage

# Session and data files
SESSION_FILE = 'anon.session'
SENT_IDS_FILE = 'sent_ids.txt'
ERRORS_FILE = 'errors.txt'

async def get_input(prompt, is_phone=False, is_password=False, default=None):
    """Get user input with optional masking and default values"""
    if is_password:
        import getpass
        prompt_text = prompt
        if default:
            prompt_text += f" [default: ******]: "
        return getpass.getpass(prompt_text) or default
    
    prompt_text = prompt
    if default:
        prompt_text += f" [default: {default}]: "
    
    if is_phone:
        while True:
            phone = input(prompt_text) or default
            if phone and phone.startswith('+') and phone[1:].isdigit():
                return phone
            print("Please enter phone number in international format (+1234567890)")
    else:
        return input(prompt_text) or default

async def get_config_from_input():
    """Get configuration from user input"""
    print("\nTelegram Channel Copier - Configuration\n")
    
    # Try to load previous config from session metadata
    prev_api_id = None
    prev_api_hash = None
    prev_phone = None
    if os.path.exists(SESSION_FILE):
        try:
            client = TelegramClient(SESSION_FILE, 0, "")
            await client.connect()
            if await client.is_user_authorized():
                session_info = client.session
                prev_api_id = getattr(session_info, 'api_id', None)
                prev_api_hash = getattr(session_info, 'api_hash', None)
                prev_phone = getattr(session_info, '_phone', None)
            await client.disconnect()
        except:
            pass
    
    config = {
        'api_id': await get_input("Enter your API ID: ", default=prev_api_id),
        'api_hash': await get_input("Enter your API Hash: ", default=prev_api_hash),
        'phone_number': await get_input("Enter your phone number (+1234567890): ", is_phone=True, default=prev_phone),
        'source_channel': await get_input("Enter source channel name (exact match): "),
        'target_channel': await get_input("Enter target channel name (exact match): ")
    }
    
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
    # Get configuration from user input
    config = await get_config_from_input()
    
    # Initialize client
    client = TelegramClient(SESSION_FILE, int(config['api_id']), config['api_hash'])
    
    # Connect to Telegram
    try:
        await client.start(phone=config['phone_number'])
    except Exception as e:
        print(f"Failed to connect: {str(e)}")
        return
    
    # Get source and target channels
    try:
        source_entity = await get_entity_by_name(client, config['source_channel'])
        target_entity = await get_entity_by_name(client, config['target_channel'])
    except Exception as e:
        print(str(e))
        return
    
    # Load already sent message IDs
    sent_ids = load_sent_ids()
    
    # Get all messages from source channel
    print(f"\nFetching messages from '{config['source_channel']}'...")
    messages = []
    async for message in client.iter_messages(source_entity):
        messages.append(message)
    
    # Filter out already sent messages
    new_messages = [msg for msg in messages if msg.id not in sent_ids]
    
    if not new_messages:
        print("No new messages to copy.")
        return
    
    print(f"Found {len(new_messages)} new messages to copy to '{config['target_channel']}'")
    
    # Copy messages with progress bar
    with tqdm(total=len(new_messages), desc="Copying messages") as pbar:
        for message in reversed(new_messages):  # Copy in chronological order
            await copy_message(client, source_entity, target_entity, message, pbar)
    
    print("\nDone!")

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
