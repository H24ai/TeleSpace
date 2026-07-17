import os
import sys
from dotenv import load_dotenv

# تحميل ملف .env للمتغيرات (للتشغيل المحلي)
load_dotenv()

# =========================================================
# 1. إعدادات المسارات (Project Paths)
# =========================================================
# تحديد المجلد الرئيسي (داخل الدوكر سيكون /app)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PROFILES_DIR = os.path.join(STATIC_DIR, "profiles")
THUMBNAILS_DIR = os.path.join(STATIC_DIR, "thumbnails")

# =========================================================
# 2. المتغيرات الأساسية (كما كانت في الكود القديم)
# =========================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEVELOPER_NAME = "Hassan AL-Naqeeb"
DEVELOPER_ID = 5372240626
DATABASE_URL = os.getenv("DATABASE_URL")

# إعدادات القنوات
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID"))
REQUIRED_CHANNEL_ID = int(os.getenv("REQUIRED_CHANNEL_ID", "-1003093025900"))
REQUIRED_CHANNEL_LINK = os.getenv("REQUIRED_CHANNEL_LINK", "https://t.me/TeleSpace_0")

# متغيرات الذكاء الاصطناعي والمفاتيح
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
VICTIM_BOT_TOKEN = os.getenv("VICTIM_BOT_TOKEN")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")

# =========================================================
# 3. المنطق الذكي للسيرفر المحلي (The Smart Logic)
# =========================================================
# جلب بيانات الاعتماد الخاصة بـ MTProto (مطلوبة للسيرفر المحلي)
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")

# التحقق هل نعمل في وضع السيرفر المحلي؟
# القيمة تأتي من Docker Environment
USE_LOCAL_SERVER = os.getenv("TELEGRAM_LOCAL", "0") == "1"

# رابط السيرفر (داخل الدوكر يكون http://telegram-bot-api:8081)
API_SERVER_URL = os.getenv("API_SERVER_URL", "http://telegram-bot-api:8081")

# هنا يكمن السحر: تحديد الروابط تلقائياً
if USE_LOCAL_SERVER:
    # ------------------ Local Mode ------------------
    # هذه المتغيرات ستحل محل os.getenv القديم لديك
    LOCAL_API_URL = f"{API_SERVER_URL}/bot"
    LOCAL_FILE_URL = f"{API_SERVER_URL}/file/bot"
    
    # نستخدم هذه المتغيرات في ApplicationBuilder
    BASE_URL = LOCAL_API_URL
    FILE_URL = LOCAL_FILE_URL
    
    # المسار الثابت للملفات داخل الحاوية
    TELEGRAM_FILES_ROOT = "/var/lib/telegram-bot-api"
    print(f"🚀 Config: Running in LOCAL SERVER mode connecting to {API_SERVER_URL}")

else:
    # ------------------ Cloud Mode ------------------
    # القيم الافتراضية لسيرفرات تيليجرام الرسمية
    BASE_URL = "https://api.telegram.org/bot"
    FILE_URL = "https://api.telegram.org/file/bot"
    
    # لضمان عدم حدوث خطأ إذا استخدمت المتغيرات القديمة
    LOCAL_API_URL = BASE_URL
    LOCAL_FILE_URL = FILE_URL
    
    TELEGRAM_FILES_ROOT = None
    print("☁️ Config: Running in CLOUD mode (Standard Telegram API)")

# =========================================================
# 4. التحقق من الصحة (Validation)
# =========================================================
# تاريخ القطع للنسخ الموزع المباشر
from datetime import datetime
cutoff_date_str = os.getenv("CUTOFF_DATE")
CUTOFF_DATE = None
if cutoff_date_str:
    try:
        cutoff_date_str = cutoff_date_str.strip().strip('"').strip("'")
        if 'T' in cutoff_date_str:
            CUTOFF_DATE = datetime.fromisoformat(cutoff_date_str)
        else:
            try:
                CUTOFF_DATE = datetime.strptime(cutoff_date_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                CUTOFF_DATE = datetime.strptime(cutoff_date_str, "%Y-%m-%d")
        print(f"📅 Config: CUTOFF_DATE loaded successfully: {CUTOFF_DATE}")
    except Exception as e:
        print(f"⚠️ Config: Error parsing CUTOFF_DATE '{cutoff_date_str}': {e}")

# هذا الكود يعمل تلقائياً عند استيراد الملف
if not TELEGRAM_BOT_TOKEN or not DATABASE_URL:
    # نستخدم sys.exit لإيقاف البرنامج فوراً إذا كانت الإعدادات ناقصة
    print("🔴 CRITICAL ERROR: Missing TELEGRAM_BOT_TOKEN or DATABASE_URL.")
    sys.exit(1)

if not API_SECRET_KEY:
    print("⚠️ Warning: API_SECRET_KEY is missing. Mobile app authentication might fail.")

if USE_LOCAL_SERVER and not (API_ID and API_HASH):
     print("⚠️ Warning: Running in Local Mode but API_ID/API_HASH are missing in .env!")