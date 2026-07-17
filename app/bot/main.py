from telegram import Update
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters
)

# نستورد كل الأدوات اللازمة من ملفاتنا
from app.shared import config
from app.shared.constants import *
import app.bot.handlers as handlers

def main() -> None:
    """
    [معدل] نقطة انطلاق البوت مع المعالجات الموحدة.
    """
    # 0. Automatic database initialization
    from app.shared.database.setup import setup_database
    setup_database()

    # 1. إنشاء التطبيق
    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .base_url(config.LOCAL_API_URL)      # توجيه الأوامر للسيرفر المحلي
        .base_file_url(config.LOCAL_FILE_URL) # توجيه الملفات للسيرفر المحلي
        .build()
    )

    # 2. إعداد وتسجيل المعالجات (Handlers)

    # [جديد] Middleware لتحديث بيانات المستخدم (يعمل مع كل تحديث)
    from telegram.ext import TypeHandler
    application.add_handler(TypeHandler(Update, handlers.check_user_updates), group=-1)

    # معالج محادثة موحد لإنشاء الحاويات (أقسام ومجلدات)
    create_container_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.new_container_prompt, pattern="^new_container_root:"),
            CallbackQueryHandler(handlers.new_container_prompt, pattern="^new_container_sub:")
        ],
        states={AWAITING_CONTAINER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_container_name)]},
        fallbacks=[CommandHandler("cancel", handlers.cancel_conversation), CommandHandler("info", handlers.info), CommandHandler("start", handlers.start)]
    )

    # معالج محادثة موحد لإعادة تسمية الحاويات
    rename_container_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handlers.rename_container_prompt, pattern="^rename_container:")],
        states={AWAITING_RENAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_new_container_name)]},
        fallbacks=[CommandHandler("cancel", handlers.cancel_conversation), CommandHandler("info", handlers.info), CommandHandler("start", handlers.start)]
    )

    # معالج محادثة إضافة العناصر إلى مجلد
    add_items_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers.add_items_start, pattern="^add_items:"),
            CommandHandler("start", handlers.start)
        ],
        states={
            AWAITING_ITEMS_FOR_UPLOAD: [
                CommandHandler("done", handlers.save_items),
                MessageHandler(filters.ALL & ~filters.COMMAND, handlers.collect_items)
            ]
        },
        fallbacks=[CommandHandler("cancel", handlers.cancel_conversation), CommandHandler("info", handlers.info), CommandHandler("start", handlers.start)]
    )

    # [جديد] معالج محادثة لربط القنوات
    link_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handlers.link_channel_start, pattern="^link_channel_start:")],
        states={AWAITING_CHANNEL_FORWARD: [MessageHandler(filters.FORWARDED & filters.ChatType.PRIVATE, handlers.receive_channel_forward)]},
        fallbacks=[CommandHandler("cancel", handlers.cancel_conversation), CommandHandler("info", handlers.info), CommandHandler("start", handlers.start)]
    )

    # [جديد] معالج محادثة للمرشد الذكي
    guide_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handlers.ask_ai_guide_start, pattern="^ask_ai_guide$")],
        states={AWAITING_GUIDE_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_ai_question)]},
        fallbacks=[CommandHandler("cancel", handlers.cancel_conversation), CommandHandler("info", handlers.info), CommandHandler("start", handlers.start)]
    )

    # تسجيل كل المعالجات في التطبيق
    application.add_handler(create_container_conv)
    application.add_handler(rename_container_conv)
    application.add_handler(add_items_conv)
    application.add_handler(link_channel_conv)
    application.add_handler(guide_conv)
    
    # [جديد وموحد] معالج الأتمتة للرسائل من القنوات والمجموعات
    application.add_handler(MessageHandler(
        (filters.UpdateType.CHANNEL_POST | filters.UpdateType.EDITED_CHANNEL_POST |
        (filters.ChatType.GROUPS & ~filters.COMMAND)) & (~filters.StatusUpdate.ALL),
        handlers.entity_post_handler
    ))
    
    # [جديد] معالج لمراقبة إنشاء وتعديل المواضيع
    application.add_handler(MessageHandler(
        filters.StatusUpdate.FORUM_TOPIC_CREATED | filters.StatusUpdate.FORUM_TOPIC_EDITED,
        handlers.forum_topic_activity_handler
    ))
    
    # ثم يتم تسجيل الأوامر والمعالج العام للأزرار
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("info", handlers.info))
    application.add_handler(CommandHandler("link_group", handlers.link_group_command)) # [إضافة جديدة]
    application.add_handler(CallbackQueryHandler(handlers.check_subscription_callback, pattern="^check_subscription$"))
    application.add_handler(CallbackQueryHandler(handlers.button_press_router))
    
    # 3. تشغيل البوت
    print("Bot is running... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
