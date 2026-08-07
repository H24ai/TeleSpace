import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.helpers import escape_markdown

from app.shared import config, ai
from app.shared.database import users as db_users
from app.shared.database import containers as db_containers
from app.shared.database import auth as db_auth

from app.bot import keyboards as kb
from app.bot.utils import check_subscription
from app.shared.constants import AWAITING_GUIDE_QUESTION

# --- Circular Import Helpers ---
# We import these inside functions to avoid circular dependency at module level
# from .navigation import show_container, return_to_my_space, return_to_shared_spaces

@check_subscription
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """[معدل] يبدأ البوت ويعالج روابط المشاركة والروابط العميقة للقنوات."""
    # Import here to avoid circular dependency
    from .navigation import show_container
    
    user = update.effective_user
    db_users.add_user_if_not_exists(user_id=user.id, first_name=user.first_name)

    # [جديد] معالج الروابط العميقة (Phase 4)
    if context.args:
        arg = context.args[0]
        
        # 1. Login Handshake
        if arg.startswith("login_"):
            request_id = arg.split('_')[1]
            token = db_auth.approve_auth_request(request_id, user.id, user.first_name)
            if token:
                await update.effective_message.reply_text("✅ لقد قمت بتسجيل الدخول بنجاح إلى تطبيق TeleSpace.\n\nيمكنك الآن تصفح المحتوى من خلال التطبيق.")
            else:
                await update.effective_message.reply_text("⚠️ عذرًا، رابط تسجيل الدخول غير صالح أو منتهي الصلاحية.")
            return ConversationHandler.END

        # 2. Upload Redirect
        elif arg.startswith("upload_"):
            try:
                folder_id = int(arg.split('_')[1])
                # Import here to avoid circular imports if any
                from .upload import start_upload_from_deeplink
                return await start_upload_from_deeplink(update, context, folder_id)
            except (ValueError, IndexError):
                await update.effective_message.reply_text("⚠️ Invalid upload link.")
                # Fall through to main menu

        # 3. Existing folder deep link
        elif arg.startswith("folder_"):
            try:
                parts = arg.split('_')
                if len(parts) >= 3:
                    # _, section_id, folder_id = parts (handling legacy format if needed)
                    # Based on existing code: _, section_id_str, folder_id_str = context.args[0].split('_')
                    # But split('_') on "folder_1_2" gives ["folder", "1", "2"]
                    _, section_id_str, folder_id_str = arg.split('_')
                    section_id = int(section_id_str)
                    folder_id = int(folder_id_str)

                    # منح المستخدم صلاحية مشاهدة للقسم الرئيسي تلقائيًا
                    db_auth.grant_viewer_permission_for_section(user.id, section_id)
                    
                    # مسح بيانات المحادثة السابقة ونقل المستخدم مباشرة إلى المجلد
                    context.user_data.clear()
                    await show_container(update, context, folder_id)
                    return ConversationHandler.END
            except (ValueError, IndexError) as e:
                print(f"Error processing deep link: {e}")
                pass # Fall through to the main menu

    # معالجة روابط المشاركة الحالية
    context.user_data.clear()
    if context.args:
        token = context.args[0]
        # Ignore if it was one of the prefixes above
        if not (token.startswith("login_") or token.startswith("upload_") or token.startswith("folder_")):
             share = db_auth.get_share_by_token(token)
             
             if share and not share['is_used']:
                 details = db_containers.get_container_details(share['content_id'])
                 if details:
                    current_permission = db_auth.get_permission_level(user.id, details['type'], share['content_id'])
                    is_already_privileged = current_permission in ['owner', 'admin']
                    container_type_ar = "قسم" if details['type'] == 'section' else "مجلد"

                    if share['link_type'] == 'admin' and is_already_privileged:
                        await update.effective_message.reply_text(f"👍 أنت بالفعل مشرف لـ {container_type_ar} '{details['name']}'.")
                    else:
                        db_auth.grant_permission(user.id, details['type'], share['content_id'], share['link_type'], can_add_admins=share['grants_can_add_admins'])
                        if share['link_type'] == 'admin':
                            db_auth.deactivate_share_link(token, user.id)
                        
                        await update.effective_message.reply_text(
                            f"✅ لقد حصلت على صلاحية وصول إلى {container_type_ar} '{details['name']}'.\n\nيمكنك تصفحه في المساحات المشتركة."
                        )
                 else:
                      await update.effective_message.reply_text("⚠️ عذرًا، المحتوى المشار إليه لم يعد موجودًا.")
             else:
                 await update.effective_message.reply_text("⚠️ عذرًا، الرابط غير صالح أو مستخدم.")

    # عرض القائمة الرئيسية
    first_name = f"[{escape_markdown(user.first_name, version=2)}](tg://user?id={user.id})"
    developer_link = f"[{escape_markdown(config.DEVELOPER_NAME, version=2)}](tg://user?id={config.DEVELOPER_ID})"
    keyboard = kb.main_menu_keyboard()
    reply_text = f"""
مرحبًا {first_name}، يسعدنا تواجدك في *TeleSpace* \! 

مساحتك الرقمية على Telegram لتحويل الفوضى إلى مساحة عمل منظمة \. 

🗂️ *نظّم* أفكارك ومشاريعك\.
💾 *احفظ* ملفاتك ورسائلك المهمة\.
🤝 *شارك* محتواك بسهولة وأمان\.
    
_استكشف مساحتك أو ابدأ بتصفح ما شاركه الآخرون معك_\.

*تطوير \| {developer_link}*
"""
    
    if update.callback_query:
        await update.callback_query.message.edit_text(reply_text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(reply_text, reply_markup=keyboard, parse_mode='MarkdownV2')
        
    return ConversationHandler.END

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends a formatted guide and cancels any ongoing conversation."""
    user_id = update.effective_user.id
    db_users.update_user_last_active(user_id)

    # Check if we are in a conversation and notify the user
    if context.user_data:
        context.user_data.clear()
        await update.message.reply_text("✅ تم إلغاء العملية الحالية.")

    info_text = """
🤖 *دليل استخدام TeleSpace*

أهلاً بك\! إليك كيفية الاستفادة القصوى من مساحتك الرقمية:

*🗂️ نظّم مساحتك ببراعة*
اذهب إلى "👤 مساحتي الخاصة" لإنشاء _أقسام_ لمواضيعك الرئيسية \(مثل "العمل"، "الدراسة"\)\.
*للتنظيم المتقدم*، يمكنك الدخول إلى أي قسم وإنشاء _أقسام فرعية_ بداخله، مما يسمح لك ببناء هيكل تنظيمي متكامل لمشاريعك\. أخيرًا، أنشئ _مجلدات_ داخل أي قسم لحفظ ملفاتك\.

*📥 احفظ كل شيء بسهولة*
داخل أي مجلد، اضغط "➕ إضافة عناصر" وأرسل ما تشاء من ملفات، صور، أو نصوص\. عند الانتهاء، اكتب `/done`\.

*ملاحظة هامة:* تُستخدم _المجلدات_ لحفظ ملفاتك ومحتوياتك، وتُستخدم _الأقسام_ لعمل تنظيم هرمي من الأقسام المتداخلة\.


*🤝 شارك بذكاء وأمان*
اضغط على زر "🔗" داخل أي قسم أو مجلد تملكه للوصول لخيارات المشاركة:

*👁️ رابط مشاهدة \(للعرض فقط\):*
• *ما هو؟* رابط دائم يمكن لأي شخص الوصول لمحتويات القسم/المجلد دون القدرة على تعديله أو حذفه\.
• *متى تستخدمه؟* مثالي لمشاركة محتواك مع آلاف المستخدمين\.

*👥 دعوة مشرف \(للتعديل والإضافة\):*
• *ما هو؟* رابط يُستخدم _لمرة واحدة فقط_ لدعوة شخص ليصبح مشرفًا على المجلد أو القسم\.
• *متى تستخدمه؟* مثالي للعمل المشترك على المشاريع، حيث يحتاج زميلك لإضافة ملفات أو تعديل المحتوى\.


*🤖 الأتمتة الذكية \(للقنوات والمجموعات\)*
حوّل البوت إلى مساعدك الذكي الذي يقوم بأرشفة المحتوى تلقائيًا\.

*📢 في القنوات:*
حوّل قناتك إلى واجهة تفاعلية ومنظمة\.
• *الإعداد:* أضف البوت إلى قناتك وامنحه صلاحيات المشرف\.
• *الربط:* في البوت، اذهب للقسم الذي تريده واربطه بالقناة\.
• *الأرشفة:* انشر رسالة في القناة مع هاشتاج يطابق اسم أحد المجلدات في قسمك\.
• *النتيجة:* سيقوم البوت بحفظ الرسالة في المجلد الصحيح ويضيف زرًا تفاعليًا تحت الرسالة الأصلية، مما يسمح للأعضاء بالوصول للمحتوى المنظم بضغطة زر\!

*👥 في المجموعات:*
نظّم محتوى مجموعاتك تلقائيًا، سواء كانت عادية أو مقسمة لمواضيع\.
• *الإعداد:* أضف البوت إلى مجموعتك وامنحه صلاحيات المشرف\.
• *الربط:* في البوت، اذهب للقسم الذي تريده واربطه بالمجموعة\.
• *الأرشفة:*
 \- *للمجموعات العادية:* انشر رسالة مع هاشتاج يطابق اسم "مجلد" في قسمك\.
 \- *للمجموعات ذات المواضيع:* انشر الرسالة في "موضوع" معين مع هاشتاج يطابق اسم "مجلد" موجود داخل "قسم فرعي" يحمل نفس اسم الموضوع\.
• *النتيجة:* سيقوم البوت بحفظ الرسالة في المكان الصحيح _بشكل صامت_، للحفاظ على سلاسة المحادثات في المجموعات\.
"""
    await update.message.reply_text(info_text, parse_mode='MarkdownV2', reply_markup=kb.back_button("back_to_main"))
    return ConversationHandler.END

@check_subscription
async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    [جديد] يتم استدعاؤه عند الضغط على زر "لقد اشتركت".
    الـ decorator سيقوم بالتحقق، وإذا نجح، سنقوم ببساطة باستدعاء دالة البدء.
    """
    query = update.callback_query
    await query.answer("✅ شكرًا لاشتراكك! أهلاً بك.", show_alert=False)

    if 'deep_link_args' in context.user_data:
        context.args = context.user_data.pop('deep_link_args')

    # بعد التحقق الناجح، نعرض القائمة الرئيسية (مع الوسائط المستعادة إن وجدت)
    await start(update, context)

# --- AI Guide Handlers ---
async def ask_ai_guide_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ محادثة المرشد الذكي."""
    query = update.callback_query
    await query.answer()
    db_users.update_user_last_active(update.effective_user.id)

    context.user_data['previous_menu'] = 'back_to_main'
    
    text = """
🤖 *مرشد TeleSpace الذكي*

أهلاً بك\! أنا هنا لمساعدتك في فهم كيفية استخدام البوت\.

**اطرح سؤالك بوضوح** \(مثال: "كيف أشارك مجلد؟" أو "ما الفرق بين القسم والمجلد؟"\)\.

سأجيبك بالاعتماد على دليل الاستخدام الرسمي للبوت\.

*للخروج من وضع الإرشاد، أرسل /cancel*\.
    """
    if query and query.message:
        await query.message.edit_text(
            text, 
            parse_mode='MarkdownV2'
        )
    
    return AWAITING_GUIDE_QUESTION

async def receive_ai_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل سؤال المستخدم، يحصل على إجابة من الذكاء الاصطناعي، ويرد."""
    question = update.message.text
    user_id = update.effective_user.id
    db_users.update_user_last_active(user_id)

    # إعطاء إشعار فوري بأن البوت "يفكر"
    thinking_message = await update.message.reply_text("🤖 جاري التفكير...", do_quote=True)

    # الحصول على الرد من الذكاء الاصطناعي
    answer = ai.get_guide_response(question)

    # تعديل رسالة "جاري التفكير" بالرد النهائي
    await thinking_message.edit_text(answer)

    # السؤال عن سؤال آخر لإبقاء المحادثة مستمرة
    await update.message.reply_text("هل لديك سؤال آخر؟ أو أرسل /cancel للخروج.")
    
    return AWAITING_GUIDE_QUESTION
