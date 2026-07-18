import re
from telegram import Message
from telegram.ext import ContextTypes
from telegram.error import Forbidden
from telegram.helpers import escape_markdown
import app.bot.keyboards as kb
import app.shared.database as db

class EntityProcessor:
    """Base class for processing updates from different entity types."""

    async def process_message(self, message: Message, linked_entity: dict, context: ContextTypes.DEFAULT_TYPE, saving_function) -> None:
        """
        Orchestrates the message processing workflow. This is the main entry point for the handler.
        """
        entity_id = message.chat.id
        message_id = message.message_id
        section_id = linked_entity['container_id']
        user_id = linked_entity['user_id']

        # 1. Get all available folders for the section.
        all_folders_in_section = db.containers.get_all_folders_recursively(section_id)
        if not all_folders_in_section:
            return # No folders to archive to.

        # 2. Determine target folders based on entity type and content.
        current_matched_folder_ids = await self.get_target_folders(message, linked_entity, all_folders_in_section)

        # 3. Get previously archived folders for this message.
        previously_archived = db.automation.get_archived_folders_for_content(entity_id, message_id)
        previously_archived_ids = set(previously_archived.keys())

        # 4. Calculate changes.
        folders_to_add = current_matched_folder_ids - previously_archived_ids
        folders_to_remove = previously_archived_ids - current_matched_folder_ids

        # 5. Execute deletions.
        for folder_id in folders_to_remove:
            item_id_to_delete = previously_archived.get(folder_id)
            if item_id_to_delete:
                db.items.delete_item(item_id_to_delete, user_id)
                db.automation.remove_archived_content(entity_id, message_id, folder_id)
                print(f"Removed item {item_id_to_delete} from folder {folder_id} for message {message_id}")

        # 6. Execute additions.
        if folders_to_add:
            item_data = await saving_function(message, context)
            if item_data:
                storage_message_id = item_data.pop('storage_message_id', None)
                storage_channel_id = item_data.pop('storage_channel_id', None)
                for folder_id in folders_to_add:
                    if folder_id not in previously_archived_ids:
                        item_id = db.items.add_item(container_id=folder_id, user_id=user_id, **item_data)
                        if item_id:
                            if storage_message_id and storage_channel_id:
                                db.items.add_file_location(
                                    item_id=item_id,
                                    channel_id=storage_channel_id,
                                    message_id=storage_message_id
                                )
                            db.automation.add_archived_content(entity_id, message_id, folder_id, item_id)
                            print(f"Archived message {message_id} to folder {folder_id} with item_id {item_id}")

        # 7. Update UI if necessary.
        final_archived_folder_ids = current_matched_folder_ids
        await self.update_ui(context, message, linked_entity, final_archived_folder_ids, all_folders_in_section)

    async def get_target_folders(self, message, linked_entity, all_folders_in_section) -> set:
        """
        Determines the target folder IDs based on the message and entity type.
        Returns a set of folder IDs.
        """
        raise NotImplementedError("Each processor must implement this method.")

    async def update_ui(self, context: ContextTypes.DEFAULT_TYPE, message, linked_entity, final_folder_ids, all_folders_in_section):
        """
        Updates the user interface (e.g., inline keyboard) after archiving.
        """
        raise NotImplementedError("Each processor must implement this method.")

class ChannelProcessor(EntityProcessor):
    """Processes messages and UI for linked channels."""
    async def get_target_folders(self, message, linked_entity, all_folders_in_section) -> set:
        text = message.text or message.caption or ""
        hashtags = set(re.findall(r"#(\w+)", text))
        normalized_hashtags = {tag.replace('_', ' ').lower() for tag in hashtags}
        
        folder_name_map = {folder['name'].lower(): folder['id'] for folder in all_folders_in_section}
        
        matched_folder_ids = {folder_name_map[ht] for ht in normalized_hashtags if ht in folder_name_map}
        return matched_folder_ids

    async def update_ui(self, context: ContextTypes.DEFAULT_TYPE, message, linked_entity, final_folder_ids, all_folders_in_section):
        folder_id_map = {folder['id']: folder['name'] for folder in all_folders_in_section}
        final_folders_for_keyboard = [
            {'id': fid, 'name': folder_id_map[fid]} 
            for fid in final_folder_ids 
            if fid in folder_id_map
        ]

        try:
            bot_username = (await context.bot.get_me()).username
            keyboard = kb.build_channel_post_keyboard(final_folders_for_keyboard, linked_entity['container_id'], bot_username)
            
            await context.bot.edit_message_reply_markup(
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=keyboard
            )
        except Forbidden as e:
            print(f"Failed to edit reply markup for message {message.message_id} in channel {message.chat.id}. Reason: {e}")
        except Exception as e:
            print(f"An unexpected error occurred while editing reply markup: {e}")

class GroupProcessor(EntityProcessor):
    """[مطور] يعالج الرسائل في المجموعات بمنطق مخصص للمجموعات ذات المواضيع."""
    async def get_target_folders(self, message: Message, linked_entity: dict, all_folders_in_section: list) -> set:
        """
        [مبسط وموحد] يحدد المجلدات المستهدفة باستخدام جدول forum_topics الموحد.
        """
        text = message.text or message.caption or ""
        hashtags = set(re.findall(r"#(\w+)", text))
        if not hashtags:
            return set()

        normalized_hashtags = {tag.replace('_', ' ').lower() for tag in hashtags}

        # إذا لم تكن المجموعة ذات مواضيع، ابحث في القسم الرئيسي مباشرة
        if not linked_entity.get('is_group_with_topics'):
            folder_name_map = {folder['name'].lower(): folder['id'] for folder in all_folders_in_section}
            return {folder_name_map[ht] for ht in normalized_hashtags if ht in folder_name_map}

        # --- منطق موحد للمجموعات ذات المواضيع ---
        
        # توحيد المعرف: استخدم 0 إذا كان None، وإلا استخدم المعرف الحقيقي
        thread_id = message.message_thread_id if message.message_thread_id is not None else 0
        
        # جلب اسم الموضوع من الجدول الموحد
        topic_name = db.automation.get_topic_name_by_thread_id(message.chat.id, thread_id)

        if not topic_name:
            if thread_id > 0:
                from app.bot.topic_fetcher import fetch_real_topic_name_via_hydrogram
                topic_name = await fetch_real_topic_name_via_hydrogram(message.chat.id, thread_id)
                if topic_name:
                    db.automation.add_or_update_topic(message.chat.id, thread_id, topic_name)
            
            if not topic_name:
                return set()

        # ابحث عن "قسم فرعي" يطابق اسم الموضوع
        all_sub_containers = db.containers.get_all_containers_recursively(linked_entity['container_id'])
        target_section = next(
            (c for c in all_sub_containers if c['type'] == 'section' and c['name'].lower() == topic_name.lower()),
            None
        )

        if not target_section:
            return set()

        # ابحث عن المجلدات داخل القسم الفرعي المطابق فقط
        folders_in_topic_section = db.containers.get_all_folders_recursively(target_section['id'])
        if not folders_in_topic_section:
            return set()
            
        folder_name_map = {folder['name'].lower(): folder['id'] for folder in folders_in_topic_section}
        return {folder_name_map[ht] for ht in normalized_hashtags if ht in folder_name_map}

    async def update_ui(self, context: ContextTypes.DEFAULT_TYPE, message: Message, linked_entity: dict, final_folder_ids: set, all_folders_in_section: list):
        # 1. تحقق أولاً مما إذا كانت هناك مجلدات تمت مطابقتها. إذا لم يكن هناك، لا تفعل شيئًا.
        if not final_folder_ids:
            return
        sender_name = message.from_user.full_name
        sender_id = message.from_user.id
        thread_id = message.message_thread_id

        # 2. بناء الأزرار التفاعلية (نفس منطق القنوات)
        folder_id_map = {folder['id']: folder['name'] for folder in all_folders_in_section}
        final_folders_for_keyboard = [
            {'id': fid, 'name': folder_id_map[fid]} 
            for fid in final_folder_ids 
            if fid in folder_id_map
        ]

        try:
            bot_username = (await context.bot.get_me()).username
            keyboard = kb.build_channel_post_keyboard(final_folders_for_keyboard, linked_entity['container_id'], bot_username)

            # 3. [مهم] حذف رسالة المستخدم الأصلية
            # يجب أن يمتلك البوت صلاحية "حذف الرسائل" في المجموعة
            await context.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)

            # 4. [مهم] إعادة إرسال المحتوى مع الأزرار
            # هذا الجزء يحتاج إلى معالجة أنواع الرسائل المختلفة (نص، صورة، ملف، الخ)
            
            # للحصول على النص أو التعليق
            sender_link = f"[{escape_markdown(sender_name, version=2)}](tg://user?id={sender_id})"
            text_or_caption = f"{escape_markdown((message.text or message.caption), version=2)}"
            caption = text_or_caption + f"\nSent by \| {sender_link}" if len(text_or_caption) <= 990 else text_or_caption[:990] + " \.\.\." + f"\nSent by \| {sender_link}"

            # التحقق من نوع الرسالة وإعادة إرسالها
            if message.photo:
                await context.bot.send_photo(
                    chat_id=message.chat.id,
                    photo=message.photo[-1].file_id,
                    caption=caption,
                    reply_markup=keyboard,
                    message_thread_id=thread_id,
                    parse_mode='MarkdownV2'
                )
            elif message.document:
                await context.bot.send_document(
                    chat_id=message.chat.id,
                    document=message.document.file_id,
                    caption=caption,
                    reply_markup=keyboard,
                    message_thread_id=thread_id,
                    parse_mode='MarkdownV2'
                )
            elif message.video:
                await context.bot.send_video(
                    chat_id=message.chat.id,
                    video=message.video.file_id,
                    caption=caption,
                    reply_markup=keyboard,
                    message_thread_id=thread_id,
                    parse_mode='MarkdownV2'
                )
            elif message.audio:
                await context.bot.send_audio(
                    chat_id=message.chat.id,
                    audio=message.audio.file_id,
                    caption=caption,
                    reply_markup=keyboard,
                    message_thread_id=thread_id,
                    parse_mode='MarkdownV2'
                )
            elif message.voice:
                await context.bot.send_voice(
                    chat_id=message.chat.id,
                    voice=message.voice.file_id,
                    caption=caption,
                    reply_markup=keyboard,
                    message_thread_id=thread_id,
                    parse_mode='MarkdownV2'
                )
            elif message.text:
                text = f"{escape_markdown(message.text, version=2)}\nSent by \| {sender_link}"
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    text=text,
                    reply_markup=keyboard,
                    message_thread_id=thread_id,
                    parse_mode='MarkdownV2'
                )

        except Forbidden as e:
            # هذا الخطأ يحدث إذا لم يكن لدى البوت الصلاحيات الكافية
            print(f"Failed to process message in group {message.chat.id}. Reason: {e}")
            # يمكنك إرسال رسالة للمالك لإعلامه بالمشكلة
            owner_id = linked_entity['user_id']
            await context.bot.send_message(
                chat_id=owner_id,
                text=f"⚠️ فشلت أتمتة الرسائل في المجموعة '{message.chat.title}'.\nالسبب: ليس لدي صلاحية 'حذف الرسائل' أو 'إرسال الرسائل'. يرجى مراجعة صلاحياتي."
            )
        except Exception as e:
            print(f"An unexpected error occurred while processing group message: {e}")

# IMPORTANT: Export PROCESSORS so it can be used by handlers
PROCESSORS = {
    'channel': ChannelProcessor(),
    'group': GroupProcessor(),
    'supergroup': GroupProcessor(),
}
