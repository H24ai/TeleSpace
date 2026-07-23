import psycopg2
import psycopg2.extras
from .core import get_db_connection, _log_activity

# --- File Location Functions ---
def add_file_location(item_id: int, channel_id: int, message_id: int):
    """
    Adds a physical file location to the file_locations table.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return

        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO file_locations (item_id, channel_id, message_id) VALUES (%s, %s, %s) ON CONFLICT (channel_id, message_id) DO NOTHING",
                (item_id, channel_id, message_id)
            )
            conn.commit()
    except psycopg2.Error as e:
        print(f"DB Error in add_file_location: {e}")
    finally:
        if conn:
            conn.close()

def get_file_location(item_id: int):
    """
    Retrieves the physical location (channel_id, message_id) for an item.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT channel_id, message_id FROM file_locations WHERE item_id = %s", (item_id,))
            return cursor.fetchone()
    except psycopg2.Error as e:
        print(f"DB Error in get_file_location: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- Item Functions ---
def add_item(container_id: int, user_id: int, item_name: str, item_type: str, content: str, file_unique_id: str = None, file_id: str = None,
             file_name: str = None, mime_type: str = None, file_size: int = None, width: int = None, height: int = None, duration: int = None, thumbnail_path: str = None) -> int | None:
    """
    Adds an item to a container, logs the activity, and returns the new item's ID.
    Includes extended metadata for files.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO items (
                    container_id, item_name, item_type, content, file_unique_id, file_id, 
                    file_name, mime_type, file_size, width, height, duration, thumbnail_path,
                    upload_date
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) 
                RETURNING item_record_id
                """,
                (container_id, item_name, item_type, content, file_unique_id, file_id,
                 file_name, mime_type, file_size, width, height, duration, thumbnail_path)
            )
            item_id = cursor.fetchone()[0]
            _log_activity(cursor, user_id, 'ADD_ITEM', item_id, 'item', f"Name: {item_name} in container {container_id}")
            conn.commit()
            return item_id
    except psycopg2.Error as e:
        print(f"DB Error in add_item: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_items_paginated(container_id: int, limit: int, offset: int):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return [], 0

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT COUNT(*) FROM items WHERE container_id = %s", (container_id,))
            total_items = cursor.fetchone()[0]
            
            cursor.execute(
                "SELECT item_record_id, item_name, item_type, content, file_id, upload_date FROM items WHERE container_id = %s ORDER BY upload_date ASC, item_record_id ASC LIMIT %s OFFSET %s",
                (container_id, limit, offset)
            )
            items_page = cursor.fetchall()
            return items_page, total_items
    except psycopg2.Error as e:
        print(f"DB Error in get_items_paginated: {e}")
        return [], 0
    finally:
        if conn:
            conn.close()

def get_item_details(item_record_id: int):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM items WHERE item_record_id = %s", (item_record_id,))
            return cursor.fetchone()
    except psycopg2.Error as e:
        print(f"DB Error in get_item_details: {e}")
        return None
    finally:
        if conn:
            conn.close()

def item_exists(item_record_id: int) -> bool:
    """
    Checks if an item with the given ID exists.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return False
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM items WHERE item_record_id = %s", (item_record_id,))
            return cursor.fetchone() is not None
    except psycopg2.Error as e:
        print(f"DB Error in item_exists: {e}")
        return False
    finally:
        if conn:
            conn.close()

def delete_item(item_record_id: int, user_id: int):
    """
    Deletes an item and logs the activity.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return

        with conn.cursor() as cursor:
            # Log first, then delete
            _log_activity(cursor, user_id, 'DELETE_ITEM', item_record_id, 'item')
            cursor.execute("DELETE FROM items WHERE item_record_id = %s", (item_record_id,))
            conn.commit()
    except psycopg2.Error as e:
        print(f"DB Error in delete_item: {e}")
    finally:
        if conn:
            conn.close()

def delete_all_items_in_container(container_id: int, user_id: int):
    """
    Deletes all items in a container and logs the activity.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return 0

        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM items WHERE container_id = %s", (container_id,))
            count = cursor.rowcount
            if count > 0:
                _log_activity(cursor, user_id, 'DELETE_ALL_ITEMS', container_id, 'container', f"Deleted {count} items.")
            conn.commit()
            return count
    except psycopg2.Error as e:
        print(f"DB Error in delete_all_items_in_container: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def rename_item(item_record_id: int, new_name: str, user_id: int) -> dict | None:
    """
    Renames an item and logs the activity. Returns the updated item dict.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(
                "UPDATE items SET item_name = %s WHERE item_record_id = %s RETURNING item_record_id, item_name", 
                (new_name, item_record_id)
            )
            updated_item = cursor.fetchone()
            
            if updated_item:
                _log_activity(cursor, user_id, 'RENAME_ITEM', item_record_id, 'item', f"New Name: {new_name}")
                conn.commit()
                return dict(updated_item)
            return None
    except psycopg2.Error as e:
        print(f"DB Error in rename_item: {e}")
        return None
    finally:
        if conn:
            conn.close()

def search_user_files(user_id: int, query: str = "", limit: int = 50, is_media_mode: bool = False):
    """
    Searches for files accessible by the user. 
    If is_media_mode is True, filters for photos/videos. 
    Otherwise, filters for documents, audio, and other files (excluding photos/videos).
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return []

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            # صياغة شرط الفلترة بناءً على وضع العرض
            if is_media_mode:
                type_condition = "i.item_type IN ('photo', 'image', 'video')"
            else:
                type_condition = "i.item_type NOT IN ('photo', 'image', 'video')"

            if query.strip():
                # Full-Text Search مع تصفية النوع
                search_query = query.strip()
                cursor.execute(f"""
                    SELECT DISTINCT i.item_record_id, i.item_name, i.content, i.file_id, i.item_type, i.file_name, i.upload_date
                    FROM items i
                    JOIN containers c ON i.container_id = c.id
                    LEFT JOIN permissions p ON c.id = p.content_id AND p.content_type IN ('section', 'folder')
                    WHERE (c.owner_user_id = %s OR p.user_id = %s)
                    AND i.file_id IS NOT NULL
                    AND i.item_type != 'text'
                    AND ({type_condition})
                    AND to_tsvector('simple', COALESCE(i.item_name, '') || ' ' || COALESCE(i.content, '') || ' ' || COALESCE(i.file_name, '')) @@ websearch_to_tsquery('simple', %s)
                    ORDER BY i.upload_date DESC
                    LIMIT %s
                """, (user_id, user_id, search_query, limit))
            else:
                # الاستعلام عند فراغ خانة البحث (جلب أحدث الملفات المفلترة)
                cursor.execute(f"""
                    SELECT DISTINCT i.item_record_id, i.item_name, i.content, i.file_id, i.item_type, i.file_name, i.upload_date
                    FROM items i
                    JOIN containers c ON i.container_id = c.id
                    LEFT JOIN permissions p ON c.id = p.content_id AND p.content_type IN ('section', 'folder')
                    WHERE (c.owner_user_id = %s OR p.user_id = %s)
                    AND i.file_id IS NOT NULL
                    AND i.item_type != 'text' 
                    AND ({type_condition})
                    ORDER BY i.upload_date DESC
                    LIMIT %s
                """, (user_id, user_id, limit))
            
            return cursor.fetchall()
    except psycopg2.Error as e:
        print(f"DB Error in search_user_files: {e}")
        return []
    finally:
        if conn:
            conn.close()