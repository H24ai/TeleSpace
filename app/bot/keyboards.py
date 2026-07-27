from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from app.shared.database import containers as db_containers
from app.shared.database import auth as db_auth
from app.shared.database import automation as db_automation
from app.shared import config

def build_my_space_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    [معدل] تبني لوحة مفاتيح للمساحة الشخصية للمستخدم.
    """
    keyboard_layout = []
    root_containers = db_containers.get_root_containers(user_id)

    # عرض الحاويات التي يملكها المستخدم فقط
    owned_containers = [c for c in root_containers if c['owner_user_id'] == user_id]

    for container in owned_containers:
        icon = "🗂️" if container['type'] == 'section' else "📁"
        container_button = InlineKeyboardButton(
            f"{icon} {container['name']}", 
            callback_data=f"container:{container['id']}"
        )
        keyboard_layout.append([container_button])
        
    # أزرار إضافة جديدة
    control_buttons = [
        InlineKeyboardButton("➕ قسم", callback_data="new_container_root:section"),
        InlineKeyboardButton("➕ مجلد", callback_data="new_container_root:folder")
    ]
    keyboard_layout.append(control_buttons)
    
    keyboard_layout.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(keyboard_layout)

def build_shared_spaces_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    [معدل] تبني لوحة مفاتيح للمساحات المشتركة.
    """
    keyboard_layout = []
    shared_containers = db_containers.get_shared_containers_for_user(user_id)

    for container in shared_containers:
        icon = "🗂️" if container['type'] == 'section' else "📁"
        # لا نعرض إلا الحاويات التي للمستخدم صلاحية مباشرة عليها في هذه القائمة
        container_button = InlineKeyboardButton(
            f"🔗 {icon} {container['name']}", 
            callback_data=f"container:{container['id']}"
        )
        # يمكن إضافة أزرار تحكم خاصة بالعناصر المشتركة هنا إذا لزم الأمر
        keyboard_layout.append([container_button])

    keyboard_layout.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(keyboard_layout)

def build_container_view_keyboard(container_id: int, user_id: int) -> InlineKeyboardMarkup:
    """
    [موحد] يبني واجهة عرض الحاوية (قسم أو مجلد) بشكل ديناميكي.
    """
    keyboard_layout = []
    container_details = db_containers.get_container_details(container_id)
    if not container_details:
        return InlineKeyboardMarkup([[InlineKeyboardButton("❌ خطأ: الحاوية غير موجودة", callback_data="my_space")]])

    permission = db_auth.get_permission_level(user_id, container_details['type'], container_id)

    # Add Settings and Share buttons for the current container
    top_buttons = []
    if permission in ['owner', 'admin']:
        top_buttons.append(InlineKeyboardButton("⚙️", callback_data=f"settings_container:{container_id}"))
    if permission in ['owner', 'admin']:
        top_buttons.append(InlineKeyboardButton("🔗", callback_data=f"share_menu_container:{container_id}"))
    
    # Add Leave button only for directly shared containers (not owned)
    is_directly_shared = db_auth.has_direct_permission(user_id, container_details['type'], container_id)
    if is_directly_shared and permission != 'owner':
        if permission == 'admin':
            top_buttons.append(InlineKeyboardButton("🚪 مغادرة", callback_data=f"leave_item_prompt_container:{container_id}"))
        elif permission == 'viewer':
            # Insert at the beginning of the keyboard_layout for viewers
            keyboard_layout.insert(0, [InlineKeyboardButton("🚪 مغادرة", callback_data=f"leave_item_prompt_container:{container_id}")])

    if top_buttons:
        keyboard_layout.append(top_buttons)

    # عرض المحتويات الفرعية (أقسام ومجلدات)
    child_containers = db_containers.get_child_containers(container_id)
    for child in child_containers:
        child_permission = db_auth.get_permission_level(user_id, child['type'], child['id'])
        prefix = "" if child_permission == 'owner' else "🔗 "
        icon = "🗂️" if child['type'] == 'section' else "📁"
        
        child_button = InlineKeyboardButton(f"{prefix}{icon} {child['name']}", callback_data=f"container:{child['id']}")
        keyboard_layout.append([child_button])

    # أزرار الإجراءات بناءً على نوع الحاوية الحالية
    action_buttons = []
    
    # Buttons for owner/admin
    if permission in ['owner', 'admin']:
        if container_details['type'] == 'section':
            action_buttons.extend([
                InlineKeyboardButton("➕ قسم فرعي", callback_data=f"new_container_sub:{container_id}:section"),
                InlineKeyboardButton("➕ مجلد جديد", callback_data=f"new_container_sub:{container_id}:folder")
            ])
        elif container_details['type'] == 'folder':
            action_buttons.append(InlineKeyboardButton("➕ إضافة عناصر", callback_data=f"add_items:{container_id}"))
    
    # "View Contents" button for owner, admin, and viewer if it's a folder
    if container_details['type'] == 'folder' and permission in ['owner', 'admin', 'viewer']:
        action_buttons.append(InlineKeyboardButton("📂 عرض المحتويات", callback_data=f"view_items:{container_id}:0"))

    if action_buttons:
        keyboard_layout.append(action_buttons)

    # زر الرجوع
    back_button_data = db_containers.get_back_navigation(user_id, container_id)
    keyboard_layout.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_button_data)])
    
    return InlineKeyboardMarkup(keyboard_layout)

def build_item_view_keyboard(container_id: int, current_offset: int, total_items: int, page_size: int) -> InlineKeyboardMarkup:
    """
    [محدث] يبني زر التنقل لعرض العناصر التالية.
    """
    keyboard = []
    
    # Only show "Show next X items" button if there are more items
    if current_offset < total_items:
        remaining_items = total_items - current_offset
        button_text = f"عرض الـ{min(page_size, remaining_items)} عناصر التالية📥"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_items:{container_id}:{current_offset}")])
        
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"container:{container_id}")])
    return InlineKeyboardMarkup(keyboard)

def build_settings_keyboard(container_id: int, user_id: int) -> InlineKeyboardMarkup:
    """
    [موحد] يبني قائمة الإعدادات للحاوية.
    """
    details = db_containers.get_container_details(container_id)
    permission = db_auth.get_permission_level(user_id, details['type'], container_id)

    keyboard = [
        [InlineKeyboardButton("✏️ إعادة تسمية", callback_data=f"rename_container:{container_id}")],
        [InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_container_prompt:{container_id}")]
    ]

    # [معدل] Use the new automation menu
    if details['type'] == 'section' and permission == 'owner':
        keyboard.insert(0, [InlineKeyboardButton("🤖 الأتمتة الذكية", callback_data=f"automation_menu:{container_id}")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"container:{container_id}")])
    return InlineKeyboardMarkup(keyboard)

def build_share_menu_keyboard(container_id: int, user_id: int) -> InlineKeyboardMarkup:
    """
    [موحد] يبني قائمة المشاركة للحاوية.
    """
    keyboard = [
        [InlineKeyboardButton("👁️ رابط مشاهدة", callback_data=f"get_viewer_link:{container_id}")]
    ]

    # [جديد] تحقق من صلاحية إضافة مشرفين
    if db_auth.can_user_add_admins(user_id, container_id):
        keyboard.append([InlineKeyboardButton("👥 إضافة مشرف", callback_data=f"get_admin_link:{container_id}")])

    keyboard.extend([
        [InlineKeyboardButton("📊 إحصائيات", callback_data=f"statistics_container:{container_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"container:{container_id}")]
    ])
    return InlineKeyboardMarkup(keyboard)

def build_automation_keyboard(container_id: int) -> InlineKeyboardMarkup:
    """
    [معدل وجديد] يبني لوحة مفاتيح التحكم في ميزة الأتمتة.
    """
    linked_entity = db_automation.get_linked_entity_by_container(container_id)
    keyboard = []

    if not linked_entity:
        # No entity linked yet
        keyboard.append([InlineKeyboardButton("🔗 ربط قناة", callback_data=f"link_channel_start:{container_id}")])
        keyboard.append([InlineKeyboardButton("👥 ربط مجموعة", callback_data=f"link_group_start:{container_id}")])
    else:
        # An entity is linked
        entity_type_str = "القناة" if linked_entity['entity_type'] == 'channel' else "المجموعة"
        
        if linked_entity['is_watching']:
            keyboard.append([InlineKeyboardButton(f"⏸️ إيقاف مراقبة {entity_type_str}", callback_data=f"stop_watch:{container_id}")])
        else:
            keyboard.append([InlineKeyboardButton(f"▶️ بدء مراقبة {entity_type_str}", callback_data=f"start_watch:{container_id}")])
        
        # Control buttons for the link
        keyboard.append([InlineKeyboardButton(f"🗑️ إلغاء ربط {entity_type_str}", callback_data=f"unlink_entity_prompt:{container_id}")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع للإعدادات", callback_data=f"settings_container:{container_id}")])
    return InlineKeyboardMarkup(keyboard)

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    [معدل] يبني القائمة الرئيسية.
    """
    keyboard = [
        [InlineKeyboardButton("👤 مساحتي الخاصة", callback_data="my_space")],
        [InlineKeyboardButton("🤝 المساحات المشتركة", callback_data="shared_spaces")],
        [
            # InlineKeyboardButton("🖼️ البحث عن الصور والفيديو", switch_inline_query_current_chat="-m "),
            InlineKeyboardButton("🔍 البحث عن الملفات", switch_inline_query_current_chat="")
        ],
        [InlineKeyboardButton("🤖 سؤال للمرشد الذكي", callback_data="ask_ai_guide")] # [جديد]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_button(callback_data: str) -> InlineKeyboardMarkup:
    """
    [جديد] ينشئ زر رجوع بسيط.
    """
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=callback_data)]])

def build_subscription_keyboard() -> InlineKeyboardMarkup:
    """
    [جديد] يبني لوحة المفاتيح التي تطلب من المستخدم الاشتراك في القناة.
    """
    keyboard = [
        [InlineKeyboardButton("🔗 الانضمام إلى القناة", url=config.REQUIRED_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ لقد اشتركت", callback_data="check_subscription")]
    ]
    return InlineKeyboardMarkup(keyboard)



def build_channel_post_keyboard(folders: list, section_id: int, bot_username: str) -> InlineKeyboardMarkup | None:
    """
    [جديد] يبني لوحة أزرار تفاعلية للرسالة في القناة.
    """
    if not folders:
        return None

    buttons = []
    for folder in folders:
        # كل زر هو رابط عميق يوجه المستخدم إلى المجلد داخل البوت
        url = f"https://t.me/{bot_username}?start=folder_{section_id}_{folder['id']}"
        buttons.append(InlineKeyboardButton(text=f"📁 {folder['name']}", url=url))
    
    # تنظيم الأزرار في صفوف، كل صف يحتوي على زرين
    keyboard_layout = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    
    return InlineKeyboardMarkup(keyboard_layout)
