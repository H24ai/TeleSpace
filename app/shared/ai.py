import os
from zerollm import ZeroLLM
from . import config

# مسار ملف قاعدة المعرفة
KNOWLEDGE_BASE_FILE = os.path.join(os.path.dirname(__file__), 'knowledge_base.md')

# قراءة محتوى قاعدة المعرفة مرة واحدة عند بدء التشغيل
try:
    with open(KNOWLEDGE_BASE_FILE, 'r', encoding='utf-8') as f:
        KNOWLEDGE_BASE_CONTENT = f.read()
except FileNotFoundError:
    KNOWLEDGE_BASE_CONTENT = "خطأ: ملف knowledge_base.md غير موجود."

def get_guide_response(question: str) -> str:
    """
    Sends a user's question along with the knowledge base to the AI using ZeroLLM.
    """
    if not config.OPENROUTER_API_KEY or config.OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY":
        return "⚠️ لم يتم تكوين مفتاح OpenRouter API. يرجى إضافته إلى ملف `config.py` أو متغيرات البيئة."

    if "خطأ" in KNOWLEDGE_BASE_CONTENT:
        return f"⚠️ لا يمكن الوصول إلى قاعدة المعرفة: {KNOWLEDGE_BASE_CONTENT}"

    system_prompt = """
أنت "مرشد TeleSpace الذكي". مهمتك هي الإجابة على أسئلة المستخدم حول كيفية استخدام بوت تليجرام "TeleSpace" بالاعتماد **فقط** على المعلومات المتوفرة في "قاعدة المعرفة" المرفقة. لا تخترع أي معلومات أو ميزات غير موجودة في النص. إذا كان السؤال غير مرتبط بوظائف البوت أو كانت الإجابة غير موجودة في قاعدة المعرفة، أجب بـ: 'عذرًا، ليس لدي معلومات حول هذا الموضوع. أنا متخصص فقط في الإجابة عن كيفية استخدام بوت TeleSpace.' كن دقيقًا ومباشرًا في إجاباتك.
"""

    try:
        # تحديد اسم النموذج والـ base_url عند تهيئة العميل
        client = ZeroLLM(
            api_key=config.OPENROUTER_API_KEY
        )

        user_content = f"""قاعدة المعرفة:
---
{KNOWLEDGE_BASE_CONTENT}
---

سؤال المستخدم: {question}"""

        # دالة chat تُمرر لها قائمة الرسائل فقط
        response = client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
        )

        return response

    except Exception as e:
        print(f"Error executing ZeroLLM Client: {e}")
        return f"⚠️ حدث خطأ أثناء الاتصال بالذكاء الاصطناعي: {e}"