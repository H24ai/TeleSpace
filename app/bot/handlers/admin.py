from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.helpers import escape_markdown

from app.shared.database import containers as db_containers
from app.shared.database import items as db_items
from app.shared.database import users as db_users
from app.shared.database import auth as db_auth
from app.shared.constants import AWAITING_CONTAINER_NAME, AWAITING_RENAME_INPUT
from app.bot import keyboards as kb

# from .navigation import show_container, return_to_my_space, return_to_shared_spaces
# Imported inside functions to avoid circle

# (1) New Container Conversation
async def new_container_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    db_users.update_user_last_active(update.effective_user.id)
    
    parts = query.data.split(':')
    context.user_data['container_type'] = parts[-1]
    parent_id = None
    if len(parts) == 3:
        parent_id = int(parts[1])
        if not db_containers.container_exists(parent_id):
            await query.answer("⚠️ عذرًا، يبدو أن المجلد الأصل قد تم حذفه بالفعل.", show_alert=False)
            await query.message.delete()
            return ConversationHandler.END
        context.user_data['previous_menu'] = f"container:{parent_id}"
    else:
        context.user_data['previous_menu'] = "my_space"
    context.user_data['parent_id'] = parent_id
    
    type_text = "القسم" if context.user_data['container_type'] == 'section' else "المجلد"
    await query.message.edit_text(text=f"📝 أرسل اسم {type_text} الجديد:\n\n*لإلغاء العملية، أرسل /cancel*")
    return AWAITING_CONTAINER_NAME

async def receive_container_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Import here to avoid circular dependency
    from .navigation import show_container, return_to_my_space
    from .main_menu import start

    # --- Robustness Check ---
    if 'container_type' not in context.user_data:
        await update.message.reply_text("⚠️ عذرًا، يبدو أن العملية قد انقطعت. يرجى المحاولة مرة أخرى من البداية.")
        context.user_data.clear()
        await start(update, context) # Go back to the main menu
        return ConversationHandler.END

    user_id = update.effective_user.id
    name = update.message.text.strip()

    if not (1 <= len(name) <= 100):
        await update.message.reply_text("⚠️ الاسم غير صالح. يجب أن يكون طوله بين 1 و 100 حرف. يرجى المحاولة مرة أخرى.\n\n*لإلغاء العملية، أرسل /cancel*")
        return AWAITING_CONTAINER_NAME

    container_type = context.user_data['container_type']
    parent_id = context.user_data.get('parent_id')

    owner_id = user_id
    if parent_id:
        if not db_containers.container_exists(parent_id):
            await update.message.reply_text("⚠️ عذرًا، يبدو أن المجلد الأصل الذي تحاول الإضافة إليه قد تم حذفه.")
            context.user_data.clear()
            await return_to_my_space(update, context)
            return ConversationHandler.END
        
        parent_details = db_containers.get_container_details(parent_id)
        if parent_details: owner_id = parent_details['owner_user_id']

    db_containers.add_container(owner_user_id=owner_id, name=name, type=container_type, parent_id=parent_id)
    await update.message.reply_text(f"✅ تم إنشاء '{name}' بنجاح.")
    
    context.user_data.clear()
    if parent_id:
        await show_container(update, context, parent_id)
    else:
        await return_to_my_space(update, context)
    return ConversationHandler.END

# (2) Rename Container Conversation
async def rename_container_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    db_users.update_user_last_active(update.effective_user.id)
    
    container_id = int(query.data.split(':')[1])

    details = db_containers.get_container_details(container_id)
    if not details:
        await query.answer("⚠️ عذرًا، يبدو أن هذا العنصر قد تم حذفه بالفعل.", show_alert=False)
        await query.message.delete()
        return ConversationHandler.END

    context.user_data['container_to_rename'] = container_id
    context.user_data['previous_menu'] = f"container:{container_id}"
    
    await query.message.edit_text(f"📝 الاسم الحالي: *{escape_markdown(details['name'], version=2)}*\n\nأرسل الاسم الجديد\.\n\n*لإلغاء العملية، أرسل /cancel*", parse_mode='MarkdownV2')
    return AWAITING_RENAME_INPUT

async def receive_new_container_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Import here to avoid circular dependency
    from .navigation import show_container, return_to_my_space

    user_id = update.effective_user.id
    new_name = update.message.text.strip()
    container_id = context.user_data['container_to_rename']

    if not (1 <= len(new_name) <= 100):
        await update.message.reply_text("⚠️ الاسم غير صالح. يجب أن يكون طوله بين 1 و 100 حرف. يرجى المحاولة مرة أخرى.\n\n*لإلغاء العملية، أرسل /cancel*")
        return AWAITING_RENAME_INPUT

    if not db_containers.container_exists(container_id):
        await update.message.reply_text("⚠️ عذرًا، يبدو أن هذا العنصر قد تم حذفه بالفعل.")
        context.user_data.clear()
        await return_to_my_space(update, context)
        return ConversationHandler.END

    db_containers.rename_container(container_id, new_name, user_id)
    await update.message.reply_text(f"✅ تم تغيير الاسم إلى: {new_name}")
    
    context.user_data.clear()
    await show_container(update, context, container_id)
    return ConversationHandler.END

# (3) Delete Deletion Callbacks
# Note: These are called from router, not conversation logic mostly, but prompts use edit_text
async def delete_container_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    container_id = int(query.data.split(':')[1])
    details = db_containers.get_container_details(container_id)
    if not details:
        await query.answer("⚠️ عذرًا، يبدو أن هذا العنصر قد تم حذفه بالفعل.", show_alert=False)
        return await query.message.delete()

    container_type_ar = "القسم" if details['type'] == 'section' else "المجلد"
    text = f"⚠️ تحذير !\nسيتم حذف هذا {container_type_ar} وكل محتوياته نهائيًا. هل أنت متأكد؟"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔥 نعم، متأكد", callback_data=f"delete_container_confirm:{container_id}"), InlineKeyboardButton("❌ تراجع", callback_data=f"settings_container:{container_id}")]])
    await query.message.edit_text(text, reply_markup=keyboard)

async def delete_container_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Import here to avoid circular dependency
    from .navigation import show_container, return_to_my_space

    query = update.callback_query
    user_id = update.effective_user.id
    container_id = int(query.data.split(':')[1])
    
    if not db_containers.container_exists(container_id):
        await query.answer("⚠️ عذرًا، يبدو أن هذا العنصر قد تم حذفه بالفعل.", show_alert=False)
        return await query.message.delete()

    parent_id = db_containers.get_parent_container_id(container_id)
    db_containers.delete_container_recursively(container_id, user_id)
    await query.answer("✅ تم الحذف بنجاح.", show_alert=False)
    
    if parent_id and db_containers.container_exists(parent_id):
        await show_container(update, context, parent_id)
    else:
        await return_to_my_space(update, context)

async def delete_item_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, item_id, container_id = query.data.split(':')
    item_id = int(item_id)
    
    if not db_items.item_exists(item_id):
        await query.answer("العنصر لم يعد موجودًا!", show_alert=False)
        return
    item_details = db_items.get_item_details(item_id)

    text = "⚠️ هل أنت متأكد من حذف هذا العنصر؟"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ نعم", callback_data=f"delete_item_confirm:{item_id}:{container_id}"),
            InlineKeyboardButton("❌ لا", callback_data=f"undo_delete_item:{item_id}:{container_id}")
        ]
    ])
    
    try:
        if item_details['item_type'] == 'text':
            await query.message.edit_text(text, reply_markup=keyboard)
        else:
            await query.message.edit_caption(caption=text, reply_markup=keyboard)
    except Exception as e:
        print(f"Error editing message for delete prompt: {e}")
        await query.answer("حدث خطأ أثناء تحرير الرسالة.", show_alert=False)

async def delete_item_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, item_id_str, container_id_str = query.data.split(':')
    item_id = int(item_id_str)
    user_id = update.effective_user.id

    if not db_items.item_exists(item_id):
        await query.answer("⚠️ عذرًا، يبدو أن هذا العنصر قد تم حذفه بالفعل.", show_alert=False)
        return await query.message.delete()

    db_items.delete_item(item_id, user_id)
    await query.answer("✅ تم حذف العنصر بنجاح.", show_alert=False)
    await query.message.delete()

async def undo_delete_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, item_id, container_id = query.data.split(':')
    item_id = int(item_id)

    if not db_items.item_exists(item_id):
        await query.answer("العنصر لم يعد موجودًا!", show_alert=False)
        await query.message.edit_text("تم حذف هذا العنصر بالفعل.")
        return
    item_details = db_items.get_item_details(item_id)

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ حذف هذا العنصر", callback_data=f"delete_item_prompt:{item_id}:{container_id}")]
    ])

    try:
        if item_details['item_type'] == 'text':
            await query.message.edit_text(item_details['content'], reply_markup=reply_markup)
        else:
            await query.message.edit_caption(caption=item_details['content'], reply_markup=reply_markup)
    except Exception as e:
        print(f"Error restoring message: {e}")
        await query.answer("حدث خطأ أثناء استعادة الرسالة.", show_alert=False)

# Leaving Shared Items
async def leave_item_prompt_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    container_id = int(query.data.split(':')[1])
    if not db_containers.container_exists(container_id):
        await query.answer("⚠️ عذرًا، يبدو أن هذا العنصر قد تم حذفه بالفعل.", show_alert=False)
        return await query.message.delete()
    details = db_containers.get_container_details(container_id)
    container_type_ar = "القسم" if details['type'] == 'section' else "المجلد"
    text = f"⚠️ هل أنت متأكد أنك تريد مغادرة هذا {container_type_ar} المشترك؟"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ نعم، مغادرة", callback_data=f"leave_item_confirm_container:{container_id}"), InlineKeyboardButton("❌ تراجع", callback_data=f"container:{container_id}")]])
    await query.message.edit_text(text, reply_markup=keyboard)

async def leave_item_confirm_container(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Import here to avoid circular dependency
    from .navigation import return_to_shared_spaces

    query = update.callback_query
    container_id = int(query.data.split(':')[1])
    user_id = update.effective_user.id

    if not db_containers.container_exists(container_id):
        await query.answer("⚠️ عذرًا، لم تعد عضوًا هنا أو أن العنصر قد حذف.", show_alert=False)
        return await query.message.delete()
    
    details = db_containers.get_container_details(container_id)
    db_auth.revoke_permission(user_id, details['type'], container_id)
    await query.answer("✅ تمت المغادرة.", show_alert=False)
    await return_to_shared_spaces(update, context)
