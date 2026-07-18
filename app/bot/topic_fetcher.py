import logging
from hydrogram import Client
from hydrogram.raw.functions.channels import GetMessages
from hydrogram.raw.types import InputMessageID
from app.shared import config

logger = logging.getLogger(__name__)

async def fetch_real_topic_name_via_hydrogram(chat_id: int, thread_id: int) -> str | None:
    """
    اقتناص اسم الموضوع الحقيقي للبوتات عبر استدعاء النواة المباشر (GetMessages) باستخدام مكتبة Hydrogram.
    الحل العبقري المعتمد لتجاوز قيد [400 BOT_METHOD_INVALID].
    """
    if not config.API_ID or not config.API_HASH or not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Hydrogram API credentials are not fully configured in environment variables.")
        return None

    try:
        api_id = int(config.API_ID)
    except ValueError:
        logger.error(f"Invalid TELEGRAM_API_ID: {config.API_ID}")
        return None

    topic_name = None
    try:
        # تهيئة العميل مع تعطيل الـ plugins تماماً لمنع مشاكل الـ venv
        # ونستخدم خيار الجلسة في الذاكرة لمنع تخزين ملفات .session على القرص
        app = Client(
            name="telespace_topic_fetcher",
            api_id=api_id,
            api_hash=config.API_HASH,
            bot_token=config.TELEGRAM_BOT_TOKEN,
            plugins=None,
            in_memory=True
        )
        
        async with app:
            # 1. تحديث الكاش المحلي للجلسة لضمان التعرف على الـ Peer
            await app.get_chat(chat_id)
            peer = await app.resolve_peer(chat_id)
            
            # 2. الاستدعاء المباشر لطبقة الـ MTProto العميقة
            result = await app.invoke(
                GetMessages(
                    channel=peer,
                    id=[InputMessageID(id=thread_id)]
                )
            )
            # 3. استخراج الاسم من مصفوفة الـ topics المرجعة في الاستجابة
            if hasattr(result, 'topics') and result.topics:
                topic = result.topics[0]
                topic_name = topic.title
                print(f"✅ تمت عملية جلب اسم الموضوع عبر Hydrogram بنجاح! الاسم: {topic_name}")
            else:
                print("⚠️ تم الاستدعاء ولكن لم يتم العثور على بيانات الموضوع في الاستجابة.")
                
    except Exception as e:
        print(f"🚨 فشل استدعاء النواة عبر Hydrogram: {e}")
            
    return topic_name
