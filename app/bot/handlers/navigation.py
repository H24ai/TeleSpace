import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.helpers import escape_markdown

from app.shared import config
from app.shared.database import containers as db_containers
from app.shared.database import auth as db_auth
from app.shared.database import items as db_items
from app.shared.database import users as db_users
from app.shared.constants import PAGE_SIZE
from app.bot import keyboards as kb

async def return_to_my_space(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[معدل] ينقل المستخدم إلى مساحته الخاصة باستخدام الدوال الجديدة."""
    keyboard = kb.build_my_space_keyboard(update.effective_user.id)
    text = """
    👤 *مساحتك الخاصة*

    تصفح أقسامك ومجلداتك، أو أنشئ جديدًا\.
    """
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def return_to_shared_spaces(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[معدل] ينقل المستخدم إلى عرض المساحات المشتركة."""
    keyboard = kb.build_shared_spaces_keyboard(update.effective_user.id)
    text = """
    🤝 *المساحة المشتركة*

    تصفح الأقسام والمجلدات التي تمت مشاركتها معك\.
    """
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def show_container(update: Update, context: ContextTypes.DEFAULT_TYPE, container_id: int):
    """[جديد ومصحح] يعرض محتويات حاوية معينة (قسم أو مجلد)."""
    user_id = update.effective_user.id
    details = db_containers.get_container_details(container_id)

    if not details:
        if update.callback_query:
            await update.callback_query.answer("القسم أو المجلد غير موجود!", show_alert=False)
        return await return_to_my_space(update, context)

    permission = db_auth.get_permission_level(user_id, details['type'], container_id)
    if permission is None:
        if update.callback_query:
            await update.callback_query.answer("ليس لديك صلاحية الوصول.", show_alert=False)
        else:
            await update.message.reply_text("ليس لديك صلاحية الوصول.")
        return

    icon = "🗂️" if details['type'] == 'section' else "📁"
    
    if permission in ['owner', 'admin']:
        text = f"{icon} *{escape_markdown(details['name'], version=2)}*\n\nتصفح، أضف، أو قم بإدارة المحتويات\."
    else:  # viewer
        text = f"{icon} *{escape_markdown(details['name'], version=2)}*\n\nتصفح المحتويات\."
    
    keyboard = kb.build_container_view_keyboard(container_id, user_id)

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def view_and_send_container_contents(update: Update, context: ContextTypes.DEFAULT_TYPE, container_id: int, offset: int = 0):
    """[معدل] يعرض ويرسل محتويات حاوية (مجلد)."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()

    if not db_containers.container_exists(container_id):
        await context.bot.send_message(chat_id, "⚠️ عذرًا، يبدو أن هذا المجلد قد تم حذفه بالفعل.")
        return

    permission = db_auth.get_permission_level(user_id, 'folder', container_id)
    can_delete = permission in ['owner', 'admin']

    items_page, total_items = db_items.get_items_paginated(container_id, limit=PAGE_SIZE, offset=offset)
    
    if not items_page and offset == 0:
        await context.bot.send_message(chat_id, "📁 المجلد فارغ.", reply_markup=kb.back_button(f"container:{container_id}"))
        return

    if not items_page and offset > 0:
        await context.bot.send_message(chat_id, "✅ تم عرض كل العناصر.", reply_markup=kb.back_button(f"container:{container_id}"))
        return
        
    await context.bot.send_message(chat_id, f"📥 جاري إرسال {len(items_page)} عنصر...")
    
    for item in items_page:
        try:
            reply_markup = None
            if can_delete:
                reply_markup = kb.InlineKeyboardMarkup([[kb.InlineKeyboardButton("🗑️ حذف هذا العنصر", callback_data=f"delete_item_prompt:{item['item_record_id']}:{container_id}")]])
            
            item_type = item['item_type']
            content = item['content']
            file_id = item['file_id']
            
            # التحقق هل العنصر مخزن بعد أو يساوي تاريخ القطع؟
            use_new_copy_logic = False
            item_upload_date = item.get('upload_date')
            if config.CUTOFF_DATE and item_upload_date:
                naive_upload_date = item_upload_date.replace(tzinfo=None) if item_upload_date.tzinfo else item_upload_date
                naive_cutoff_date = config.CUTOFF_DATE.replace(tzinfo=None) if config.CUTOFF_DATE.tzinfo else config.CUTOFF_DATE
                if naive_upload_date >= naive_cutoff_date:
                    use_new_copy_logic = True

            sent_via_copy = False

            if use_new_copy_logic:
                # آلية الميزة الجديدة: محاولة النسخ المباشر الموزع لجميع الأنواع (نص أو وسائط) دون تعليق توضيحي مخصص (caption)
                location = db_items.get_file_location(item['item_record_id'])
                if location:
                    try:
                        await context.bot.copy_message(
                            chat_id=chat_id,
                            from_chat_id=location['channel_id'],
                            message_id=location['message_id'],
                            reply_markup=reply_markup
                        )
                        sent_via_copy = True
                    except Exception as e:
                        print(f"Failed to copy message using new copy logic for item {item['item_record_id']}: {e}")
            else:
                # آلية الطرق القديمة/الحالية: النسخ المباشر للوسائط فقط مع تعليق توضيحي مخصص (caption)
                if item_type != 'text':
                    location = db_items.get_file_location(item['item_record_id'])
                    if location:
                        try:
                            display_caption = content
                            if display_caption != None:
                                display_caption = display_caption if len(display_caption) <= 1024 else display_caption[:1020] + " ..."
                            
                            await context.bot.copy_message(
                                chat_id=chat_id,
                                from_chat_id=location['channel_id'],
                                message_id=location['message_id'],
                                caption=display_caption if display_caption else None,
                                reply_markup=reply_markup
                            )
                            sent_via_copy = True
                        except Exception as e:
                            print(f"Failed to copy message using old copy logic for item {item['item_record_id']}: {e}")

            # إذا تم الإرسال بنجاح عبر copy_message، انتقل للعنصر التالي
            if sent_via_copy:
                await asyncio.sleep(0.5)
                continue

            # الحل الاحتياطي (Fallback) في حال عدم الإرسال بنسخ الرسالة أو للمسارات القديمة للنصوص
            if item_type == 'text':
                await context.bot.send_message(chat_id=chat_id, text=content, reply_markup=reply_markup)
            else:
                display_caption = content
                if display_caption != None:
                    display_caption = display_caption if len(display_caption) <= 1024 else display_caption[:1020] + " ..."
                send_map = {
                    'document': context.bot.send_document,
                    'video': context.bot.send_video,
                    'photo': context.bot.send_photo,
                    'audio': context.bot.send_audio,
                    'voice': context.bot.send_voice,
                }
                kwargs = {'caption': display_caption, 'reply_markup': reply_markup, item_type: file_id}
                await send_map[item_type](chat_id=chat_id, **kwargs)
            
            await asyncio.sleep(0.5)
        except Exception as e:
            await context.bot.send_message(chat_id, f"⚠️ تعذر إرسال: {item['item_name']}\nالخطأ: {e}")
            
    new_offset = offset + len(items_page)
    
    if new_offset < total_items:
        keyboard = kb.build_item_view_keyboard(container_id, new_offset, total_items, PAGE_SIZE)
        await context.bot.send_message(chat_id, "👇 توجد عناصر أخرى.", reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id, "✅ تم عرض كل العناصر.", reply_markup=kb.back_button(f"container:{container_id}"))

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """[معدل] يلغي المحادثة الحالية."""
    # Import here to avoid circular dependency
    from .main_menu import start
    
    await update.message.reply_text("❌ تم إلغاء العملية. جارٍ العودة...")
    previous_menu = context.user_data.get('previous_menu')
    context.user_data.clear()

    if previous_menu:
        if previous_menu.startswith("container:"):
            container_id = int(previous_menu.split(':')[1])
            await show_container(update, context, container_id)
        elif previous_menu == "my_space":
            await return_to_my_space(update, context)
        elif previous_menu == "shared_spaces":
            await return_to_shared_spaces(update, context)
        else:
            await start(update, context)
    else:
        await start(update, context)
    return ConversationHandler.END
