from telegram import Update, Message
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import Forbidden
from telegram.helpers import escape_markdown

from app.shared import config
from app.shared.database import containers as db_containers
from app.shared.database import items as db_items
from app.shared.database import users as db_users
from app.shared.constants import AWAITING_ITEMS_FOR_UPLOAD
from app.bot import keyboards as kb

import os
import uuid # For unique filenames if needed, though file_unique_id is better

async def process_message_for_saving(message: Message, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    """
    [معدل] يعالج الرسائل:
    1. يرسلها لقناة التخزين (سواء كانت نصاً أو وسائط).
    2. يستخرج الميتاداتا من رسالة القناة.
    3. يحمل الصورة المصغرة محلياً.
    """
    file_type, file_obj = None, None
    if message.document: (file_type, file_obj) = ('document', message.document)
    elif message.video: (file_type, file_obj) = ('video', message.video)
    elif message.photo: (file_type, file_obj) = ('photo', message.photo[-1])
    elif message.audio: (file_type, file_obj) = ('audio', message.audio)
    elif message.voice: (file_type, file_obj) = ('voice', message.voice)
    elif message.text: (file_type, file_obj) = ('text', None)

    if file_type:
        try:
            fwd_msg = await message.forward(chat_id=config.STORAGE_CHANNEL_ID)
        except Forbidden:
            print(f"Error: Bot is not an admin in the storage channel {config.STORAGE_CHANNEL_ID} or cannot forward messages.")
            return None
        
        # إذا كان العنصر نصياً، يتم إرجاع بياناته فوراً بعد نجاح إعادة التوجيه
        if file_type == 'text':
            if fwd_msg:
                return {
                    'item_name': f"رسالة: {message.text[:20]}...",
                    'item_type': 'text',
                    'content': message.text,
                    'file_unique_id': None,
                    'file_id': None,
                    'storage_message_id': fwd_msg.message_id,
                    'storage_channel_id': fwd_msg.chat.id,
                    # بيانات وصفية فارغة للنص
                    'file_name': None, 'mime_type': 'text/plain', 'file_size': 0, 
                    'width': None, 'height': None, 'duration': None, 'thumbnail_path': None
                }
            else:
                print("Could not forward text message to storage channel")
                return None
        
        fwd_file_obj = None
        if fwd_msg:
            # Extract file object from the forwarded message (Source of Truth)
            if file_type == 'document' and fwd_msg.document: fwd_file_obj = fwd_msg.document
            elif file_type == 'video' and fwd_msg.video: fwd_file_obj = fwd_msg.video
            elif file_type == 'photo' and fwd_msg.photo: fwd_file_obj = fwd_msg.photo[-1] # Highest quality
            elif file_type == 'audio' and fwd_msg.audio: fwd_file_obj = fwd_msg.audio
            elif file_type == 'voice' and fwd_msg.voice: fwd_file_obj = fwd_msg.voice

        if fwd_msg and fwd_file_obj:
            # --- Metadata Extraction ---
            meta = {
                'file_name': getattr(fwd_file_obj, 'file_name', f'{file_type}_{fwd_file_obj.file_unique_id}'),
                'mime_type': getattr(fwd_file_obj, 'mime_type', None),
                'file_size': getattr(fwd_file_obj, 'file_size', 0),
                'width': getattr(fwd_file_obj, 'width', None),
                'height': getattr(fwd_file_obj, 'height', None),
                'duration': getattr(fwd_file_obj, 'duration', None),
                'thumbnail_path': None
            }

            # --- Thumbnail Processing ---
            # Try to find a thumbnail
            thumb = None
            if file_type == 'photo' and fwd_msg.photo:
                 # Use the smallest photo as thumbnail
                 thumb = fwd_msg.photo[0]
            else:
                 thumb = getattr(fwd_file_obj, 'thumbnail', None) or getattr(fwd_file_obj, 'thumb', None)
            
            if thumb:
                try:
                    save_dir = os.path.join(os.getcwd(), 'static', 'thumbnails')
                    os.makedirs(save_dir, exist_ok=True)
                    
                    filename = f"{fwd_file_obj.file_unique_id}.jpg"
                    save_path = os.path.join(save_dir, filename)
                    
                    # Check if exists locally
                    if not os.path.exists(save_path):
                        thumb_file = await context.bot.get_file(thumb.file_id)
                        await thumb_file.download_to_drive(save_path)
                    
                    meta['thumbnail_path'] = f"static/thumbnails/{filename}"
                except Exception as e:
                    print(f"Error downloading thumbnail: {e}")

            collected_data = {
                'item_name': meta['file_name'],
                'item_type': file_type,
                'content': message.caption, # Caption from original message
                'file_unique_id': fwd_file_obj.file_unique_id,
                'file_id': fwd_file_obj.file_id,
                'storage_message_id': fwd_msg.message_id,
                'storage_channel_id': fwd_msg.chat.id,
                **meta # Unpack metadata
            }
            return collected_data
        else:
            print(f"Could not forward message or extract file of type {file_type}")
            return None
        
    return None

async def add_items_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    # NOTE: User update is now handled by Middleware, so we don't strictly need to call update_user_last_active here manually,
    # but it doesn't hurt.
    db_users.update_user_last_active(update.effective_user.id)
    
    container_id = int(query.data.split(':')[1])
    if not db_containers.container_exists(container_id):
        await query.answer("⚠️ عذرًا، يبدو أن هذا المجلد قد تم حذفه بالفعل.", show_alert=False)
        await query.message.delete()
        return ConversationHandler.END

    context.user_data['target_container_id'] = container_id
    context.user_data['previous_menu'] = f"container:{container_id}"
    await query.message.edit_text(text="*➕ وضع الإضافة*\n\nأرسل ملفاتك، صورك، أو رسائلك\. \nعند الانتهاء، اضغط /done لحفظها أو /cancel للإلغاء\.", parse_mode='MarkdownV2')
    return AWAITING_ITEMS_FOR_UPLOAD


async def collect_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'items_to_add_buffer' not in context.user_data:
        context.user_data['items_to_add_buffer'] = []
    context.user_data['items_to_add_buffer'].append(update.message)
    await update.message.reply_text("👍 تم الاستلام\. أرسل المزيد أو اضغط /done للحفظ\.", parse_mode='MarkdownV2')
    return AWAITING_ITEMS_FOR_UPLOAD

async def save_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    container_id = context.user_data.get('target_container_id')
    message_buffer = context.user_data.get('items_to_add_buffer', [])

    if not db_containers.container_exists(container_id):
        await update.message.reply_text("⚠️ عذرًا، يبدو أن المجلد الذي تحاول الحفظ فيه قد تم حذفه.")
        context.user_data.clear()
        return ConversationHandler.END

    if not message_buffer:
        await update.message.reply_text("⚠️ لم ترسل أي عناصر. تم الخروج من وضع الإضافة.", reply_markup=kb.back_button(f"container:{container_id}"))
    else:
        await update.message.reply_text(f"📥 جاري حفظ {len(message_buffer)} عنصر...")
        count = 0
        for msg in message_buffer:
            # Pass context for file downloading
            item_info = await process_message_for_saving(msg, context)
            if item_info:
                # Step A: Add item metadata
                item_id = db_items.add_item(
                    container_id=container_id,
                    user_id=user_id,
                    item_name=item_info['item_name'],
                    item_type=item_info['item_type'],
                    content=item_info['content'],
                    file_unique_id=item_info['file_unique_id'],
                    file_id=item_info['file_id'],
                    # New Metadata Fields
                    file_name=item_info.get('file_name'),
                    mime_type=item_info.get('mime_type'),
                    file_size=item_info.get('file_size'),
                    width=item_info.get('width'),
                    height=item_info.get('height'),
                    duration=item_info.get('duration'),
                    thumbnail_path=item_info.get('thumbnail_path')
                )

                if item_id:
                    # Step B: Add file location if available
                    if item_info.get('storage_message_id') and item_info.get('storage_channel_id'):
                        db_items.add_file_location(
                            item_id=item_id,
                            channel_id=item_info['storage_channel_id'],
                            message_id=item_info['storage_message_id']
                        )
                    count += 1
        
        await update.message.reply_text(f"✅ تم حفظ {count} عنصر بنجاح.", reply_markup=kb.back_button(f"container:{container_id}"))
        context.user_data.clear()
        return ConversationHandler.END

async def start_upload_from_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, folder_id: int) -> int:
    """
    [Phase 4] Starts the upload conversation directly from a deep link.
    """
    user_id = update.effective_user.id
    
    # Check existence
    if not db_containers.container_exists(folder_id):
        await update.message.reply_text("⚠️ This folder no longer exists.")
        return ConversationHandler.END

    # Check permission (Basic check)
    # Ideally should check write permissions.
    details = db_containers.get_container_details(folder_id)
    if details['type'] == 'section':
         await update.message.reply_text("⚠️ Cannot upload directly to a Section. Please choose a Folder.")
         return ConversationHandler.END
         
    # Setup state
    context.user_data['target_container_id'] = folder_id
    context.user_data['previous_menu'] = f"container:{folder_id}"
    
    folder_name = escape_markdown(details['name'], version=2)
    await update.message.reply_text(
        f"📂 *Upload Mode: {folder_name}*\n\n"
        f"You are now linked to this folder via the app\.\n"
        f"Send files/messages to save them here\.\n"
        f"Type /done to finish or /cancel to exit\.",
        parse_mode='MarkdownV2'
    )
    return AWAITING_ITEMS_FOR_UPLOAD
