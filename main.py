async def main():
    config = load_config() or prompt_config()
    config = prompt_edit_channels(config)

    client = TelegramClient(SESSION_FILE, config['api_id'], config['api_hash'])
    await client.start(phone=config['phone'])

    # Get channel by title from dialogs (since we only have name, not username or ID)
    source = target = None
    async for dialog in client.iter_dialogs():
        if dialog.name == config['source_channel']:
            source = dialog.entity
        if dialog.name == config['target_channel']:
            target = dialog.entity

    if not source or not target:
        print("Source or Target channel not found in your dialogs. Are you a member?")
        return

    sent_ids = load_sent_ids()
    all_messages = []
    offset_id = 0
    limit = 100

    print("Fetching messages from source...")
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

    new_messages = [
        msg for msg in all_messages
        if isinstance(msg, Message) and msg.id not in sent_ids
    ]

    print(f"Found {len(new_messages)} new messages to copy.")

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
                if msg.message:
                    sent_msg = await client.send_message(
                        target,
                        msg.message or '',
                        parse_mode='html'
                    )
                else:
                    continue  # skip empty service messages

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
