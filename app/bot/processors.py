import re
from telegram import Message, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest
from telegram.helpers import escape_markdown
import app.bot.keyboards as kb
import app.shared.database as db


def extract_clean_hashtags(message: Message) -> set[str]:
    """
    تستخرج الهاشتاجات من أي رسالة (عادية أو غنية) بكفاءة عالية وبدون أخطاء الإيموجي (UTF-16).
    تُرجع العناصر في set مع تحويلها إلى Lowercase وإزالة الـ # واستبدال الـ _ بمسافة (' ')
    """
    if not message:
        return set()

    found_tags = set()
    message_dict = message.to_dict() if hasattr(message, 'to_dict') else {}

    # 1. المسار الأول: الرسائل الغنية (Rich Messages)
    if 'rich_message' in message_dict:
        rich_data = message_dict['rich_message']
        
        for block in rich_data.get('blocks', []):
            block_text = block.get('text')
            
            if isinstance(block_text, dict) and block_text.get('type') == 'hashtag':
                tag = block_text.get('hashtag') or block_text.get('text', '')
                if tag:
                    clean = tag.lstrip('#').replace('_', ' ').strip().lower()
                    if clean:
                        found_tags.add(clean)

            elif isinstance(block_text, list):
                for item in block_text:
                    if isinstance(item, dict) and item.get('type') == 'hashtag':
                        tag = item.get('hashtag') or item.get('text', '')
                        if tag:
                            clean = tag.lstrip('#').replace('_', ' ').strip().lower()
                            if clean:
                                found_tags.add(clean)
        
        # إذا وجدنا الهاشتاجات في الرسائل الغنية، نكتفي بها ونرجعها
        if found_tags:
            return found_tags

    # 2. المسار الثاني: الكيانات الرسمية عبر دوال المكتبة (تتجاوز مشكلة الإيموجي بأمان)
    entities_dict = {}
    if message.text:
        # نجلب الكيانات من النص
        entities_dict = message.parse_entities(types=[MessageEntity.HASHTAG])
    elif message.caption:
        # نجلب الكيانات من الشرح المرفق للوسائط (الصور/الفيديو)
        entities_dict = message.parse_caption_entities(types=[MessageEntity.HASHTAG])

    if entities_dict:
        found_tags = {
            tag_text.lstrip('#').replace('_', ' ').strip().lower()
            for entity, tag_text in entities_dict.items()
        }
        found_tags.discard('')
        
        if found_tags:
            return found_tags

    # 3. المسار الثالث: البحث الاحتياطي بالـ Regex (يدعم العربي)
    text_content = message.text or message.caption
    if text_content:
        regex_tags = re.findall(r"#([^\s#]+)", text_content)
        found_tags = {
            tag.replace('_', ' ').strip().lower()
            for tag in regex_tags
        }
        found_tags.discard('')

    return found_tags


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
    async def get_target_folders(self, message: Message, linked_entity: dict, all_folders_in_section: list) -> set:
        hashtags = extract_clean_hashtags(message)
        if not hashtags:
            return set()
        
        folder_name_map = {}
        for folder in all_folders_in_section:
            folder_name_map[folder['name'].lower()] = folder['id']
        
        matched_folder_ids = {folder_name_map[ht] for ht in hashtags if ht in folder_name_map}
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
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                print(f"BadRequest editing reply markup: {e}")
        except Exception as e:
            print(f"An unexpected error occurred while editing reply markup: {e}")

class GroupProcessor(EntityProcessor):
    """[مطور] يعالج الرسائل في المجموعات بمنطق مخصص للمجموعات ذات المواضيع."""
    async def get_target_folders(self, message: Message, linked_entity: dict, all_folders_in_section: list) -> set:
        """
        [مبسط وموحد] يحدد المجلدات المستهدفة باستخدام جدول forum_topics الموحد.
        """
        hashtags = extract_clean_hashtags(message)
        if not hashtags:
            return set()

        # إذا لم تكن المجموعة ذات مواضيع، ابحث في القسم الرئيسي مباشرة
        if not linked_entity.get('is_group_with_topics'):
            folder_name_map = {}
            for folder in all_folders_in_section:
                folder_name_map[folder['name'].lower()] = folder['id']
                folder_name_map[folder['name'].lower().replace('_', '').replace(' ', '')] = folder['id']
            return {folder_name_map[ht] for ht in hashtags if ht in folder_name_map}

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
            
        folder_name_map = {}
        for folder in folders_in_topic_section:
            folder_name_map[folder['name'].lower()] = folder['id']
            folder_name_map[folder['name'].lower().replace('_', '').replace(' ', '')] = folder['id']
        return {folder_name_map[ht] for ht in hashtags if ht in folder_name_map}

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

            # التحقق مما إذا كانت الرسالة مُرسلة من قبل "المجموعة" (أدمن مخفي)
            if message.sender_chat and message.sender_chat.id == message.chat.id:
                # محاولة جلب الوسم (إذا كان الأدمن يمتلك وسماً مخصصاً)
                admin_title = message.author_signature
                sender_name = admin_title
                
            sender_button = InlineKeyboardButton(
                text=f"Sent by | {sender_name}",
                url=f"tg://user?id={sender_id}"
            )

            if keyboard:
                keyboard_list = list(keyboard.inline_keyboard)
                keyboard_list.append([sender_button])
                keyboard = InlineKeyboardMarkup(keyboard_list)
            else:
                keyboard = InlineKeyboardMarkup([[sender_button]])

            # 3. [مهم] نسخ وإعادة إرسال الرسالة مع الأزرار التفاعلية
            await context.bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=keyboard,
                message_thread_id=thread_id
            )

            # 4. [مهم] حذف رسالة المستخدم الأصلية
            # يجب أن يمتلك البوت صلاحية "حذف الرسائل" في المجموعة
            await context.bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)

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
