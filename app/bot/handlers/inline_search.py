from telegram import (
    Update, 
    InlineQueryResultCachedDocument, 
    InlineQueryResultCachedVideo, 
    InlineQueryResultCachedPhoto, 
    InlineQueryResultCachedAudio, 
    InlineQueryResultCachedVoice
)
from telegram.ext import ContextTypes
import asyncio
import uuid

from app.shared.database.items import search_user_files

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles inline queries to search and share files seamlessly in TeleSpace.
    """
    query = update.inline_query.query.strip()
    user_id = update.inline_query.from_user.id
    
    # 1. تفعيل فلاتر الرموز بناءً على ما اتفقنا عليه لتجنب تشوه العرض
    is_media_mode = query.startswith("-m")
    if is_media_mode:
        search_query = query[2:].strip()
        # يمكنك تمرير هذا المتغير لدالة قاعدة البيانات لتصفية الوسائط فقط: WHERE item_type IN ('photo', 'video', 'image')
    else:
        search_query = query
        # وللمستندات: WHERE item_type NOT IN ('photo', 'video', 'image')
    
    # السحر هنا: هذا السطر سيشغل استعلام قاعدة البيانات في الخلفية دون تجميد البوت
    results_db = await asyncio.to_thread(search_user_files, user_id, search_query, 50, is_media_mode)
    
    inline_results = []
    fallback_map = [] 
    
    # 2. بناء النتائج
    for item in results_db:
        item_id = str(item['item_record_id'])
        file_id = item['file_id']
        
        # تنسيق النصوص لتجنب الـ NoneType Errors
        item_name = (item.get('item_name') or "").strip()
        file_name = (item.get('file_name') or "").strip()
        title = item_name or file_name or "ملف"
        content_text = (item.get('content') or "").strip()
        description = content_text
        
        if search_query and content_text:
            query_words = search_query.lower().split()
            lines = content_text.split('\n')
            matching_lines = []
            for line in lines:
                if any(word in line.lower() for word in query_words):
                    matching_lines.append(line.strip())
            if matching_lines:
                description = " ... ".join(matching_lines)
                
        if len(description) > 200:
            description = description[:197] + "..."
        elif not description:
            description = "لا يحتوي على وصف"
            
        item_type = item.get('item_type')
        
        try:
            if item_type in ['photo', 'image']:
                res = InlineQueryResultCachedPhoto(
                    id=item_id,
                    photo_file_id=file_id,
                    title=title,
                    description=description
                )
            elif item_type == 'video':
                res = InlineQueryResultCachedVideo(
                    id=item_id,
                    video_file_id=file_id,
                    title=title,
                    description=description
                )
            elif item_type == 'voice':
                # Voice لا يدعم description في تيليجرام
                res = InlineQueryResultCachedVoice(
                    id=item_id,
                    voice_file_id=file_id,
                    title=title
                )
            elif item_type == 'audio' and '.mp3' in title.lower():
                res = InlineQueryResultCachedAudio(
                    id=item_id,
                    audio_file_id=file_id,
                    caption=description
                )
            else: # document or any fallback
                res = InlineQueryResultCachedDocument(
                    id=item_id,
                    document_file_id=file_id,
                    title=title,
                    description=description
                )
                
            inline_results.append(res)
            fallback_map.append({'res_obj': res, 'file_id': file_id})
            
        except Exception:
            continue
            
    try:
        # إرسال النتائج بدون أي أزرار علوية
        await update.inline_query.answer(
            inline_results,
            cache_time=30,
            is_personal=True
        )
    except Exception as e:
        print(f"Inline query batch failed (Likely a bad file_id): {e}")
        # محاولة الحل الاحتياطي (إرسال قائمة فارغة لإلغاء جاري التحميل)
        try:
            await update.inline_query.answer([], cache_time=5, is_personal=True)
        except Exception as fallback_error:
            print(f"Fallback answer failed: {fallback_error}")