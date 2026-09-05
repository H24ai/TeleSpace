import psycopg2
import psycopg2.extras
import uuid
from .core import get_db_connection, _log_activity
from .containers import get_container_details

# --- Share and Permission Functions ---
def can_user_add_admins(user_id: int, content_id: int) -> bool:
    """
    Checks if a user is an owner or an admin with rights to add other admins.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return False
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            # أولاً، تحقق مما إذا كان المستخدم هو المالك
            cursor.execute("SELECT owner_user_id FROM containers WHERE id = %s", (content_id,))
            owner_res = cursor.fetchone()
            if owner_res and owner_res['owner_user_id'] == user_id:
                return True

            # ثانيًا، تحقق من جدول الصلاحيات بشكل هرمي
            current_id = content_id
            while current_id is not None:
                cursor.execute(
                    "SELECT can_add_admins FROM permissions WHERE user_id = %s AND content_id = %s AND permission_level = 'admin'",
                    (user_id, current_id)
                )
                perm_res = cursor.fetchone()
                if perm_res and perm_res['can_add_admins'] == 1:
                    return True
                
                # Move to the parent container
                cursor.execute("SELECT parent_id FROM containers WHERE id = %s", (current_id,))
                parent_result = cursor.fetchone()
                current_id = parent_result['parent_id'] if parent_result else None

            return False
    except psycopg2.Error as e:
        print(f"DB Error in can_user_add_admins: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_or_create_viewer_share_link(owner_user_id: int, content_type: str, content_id: int) -> str:
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT share_token FROM shares WHERE content_type = %s AND content_id = %s AND link_type = 'viewer'",
                (content_type, content_id)
            )
            existing_link = cursor.fetchone()
            if existing_link:
                return existing_link[0]
            else:
                token = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO shares (share_token, content_type, content_id, owner_user_id, link_type) VALUES (%s, %s, %s, %s, %s)",
                    (token, content_type, content_id, owner_user_id, 'viewer')
                )
                _log_activity(cursor, owner_user_id, 'CREATE_SHARE_LINK', content_id, content_type, "Type: viewer")
                conn.commit()
                return token
    except psycopg2.Error as e:
        print(f"DB Error in get_or_create_viewer_share_link: {e}")
        return None
    finally:
        if conn:
            conn.close()

def create_share_link(owner_user_id: int, content_type: str, content_id: int, link_type: str, grants_can_add_admins: int = 0) -> str: # تعديل هنا
    token = str(uuid.uuid4())
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO shares (share_token, content_type, content_id, owner_user_id, link_type, grants_can_add_admins) VALUES (%s, %s, %s, %s, %s, %s)", # تعديل هنا
                (token, content_type, content_id, owner_user_id, link_type, grants_can_add_admins) # تعديل هنا
            )
            _log_activity(cursor, owner_user_id, 'CREATE_SHARE_LINK', content_id, content_type, f"Type: {link_type}, Can Add Admins: {grants_can_add_admins}")
            conn.commit()
            return token
    except psycopg2.Error as e:
        print(f"DB Error in create_share_link: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_share_by_token(token: str):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM shares WHERE share_token = %s", (token,))
            return cursor.fetchone()
    except psycopg2.Error as e:
        print(f"DB Error in get_share_by_token: {e}")
        return None
    finally:
        if conn:
            conn.close()

def deactivate_share_link(token: str, user_id: int):
    """ Logs who used the link """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return
        with conn.cursor() as cursor:
            cursor.execute("UPDATE shares SET is_used = TRUE WHERE share_token = %s", (token,))
            _log_activity(cursor, user_id, 'USE_SHARE_LINK', details=f"Token: {token}")
            conn.commit()
    except psycopg2.Error as e:
        print(f"DB Error in deactivate_share_link: {e}")
    finally:
        if conn:
            conn.close()

def grant_permission(user_id: int, content_type: str, content_id: int, new_permission_level: str, can_add_admins: int = 0): # تعديل هنا
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return

        with conn.cursor() as cursor:
            # إذا كان المستخدم هو المالك، يجب أن يحصل على صلاحية إضافة المشرفين دائمًا
            details = get_container_details(content_id)
            if details and details['owner_user_id'] == user_id:
                new_permission_level = 'owner'
                can_add_admins = 1

            query = """
                INSERT INTO permissions (user_id, content_type, content_id, permission_level, can_add_admins)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, content_id, content_type) DO UPDATE SET
                    permission_level = EXCLUDED.permission_level,
                    can_add_admins = EXCLUDED.can_add_admins
                WHERE
                    (permissions.permission_level = 'viewer' AND EXCLUDED.permission_level = 'admin') OR
                    (permissions.permission_level = 'admin' AND EXCLUDED.permission_level = 'admin');
            """
            cursor.execute(query, (user_id, content_type, content_id, new_permission_level, can_add_admins)) # تعديل هنا

            if cursor.rowcount > 0:
                _log_activity(cursor, user_id, 'GRANT_PERMISSION', content_id, content_type, f"Level: {new_permission_level}, Can Add Admins: {can_add_admins}")
            conn.commit()
    except psycopg2.Error as e:
        print(f"DB Error in grant_permission: {e}")
    finally:
        if conn:
            conn.close()


def grant_viewer_permission_for_section(user_id: int, section_id: int):
    """
    [جديد] يمنح صلاحية مشاهدة لقسم معين بشكل آمن.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return

        with conn.cursor() as cursor:
            # يضيف الصلاحية فقط إذا لم تكن موجودة، أو يتجاهل الأمر إذا كانت موجودة
            # هذا يمنع تخفيض صلاحية المشرف إلى مشاهد
            query = """
                INSERT INTO permissions (user_id, content_type, content_id, permission_level)
                VALUES (%s, 'section', %s, 'viewer')
                ON CONFLICT (user_id, content_id, content_type) DO NOTHING;
            """
            cursor.execute(query, (user_id, section_id))
            if cursor.rowcount > 0:
                _log_activity(cursor, user_id, 'GRANT_PERMISSION', section_id, 'section', "Level: viewer (via channel button)")
            conn.commit()
    except psycopg2.Error as e:
        print(f"DB Error in grant_viewer_permission_for_section: {e}")
    finally:
        if conn:
            conn.close()

def revoke_permission(user_id: int, content_type: str, content_id: int):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return

        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM permissions WHERE user_id = %s AND content_type = %s AND content_id = %s",
                (user_id, content_type, content_id)
            )
            if cursor.rowcount > 0:
                 _log_activity(cursor, user_id, 'REVOKE_PERMISSION', content_id, content_type)
            conn.commit()
    except psycopg2.Error as e:
        print(f"DB Error in revoke_permission: {e}")
    finally:
        if conn:
            conn.close()

def has_direct_permission(user_id: int, content_type: str, content_id: int) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return False

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM permissions WHERE user_id = %s AND content_type = %s AND content_id = %s",
                (user_id, content_type, content_id)
            )
            return cursor.fetchone() is not None
    except psycopg2.Error as e:
        print(f"DB Error in has_direct_permission: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_permission_level(user_id: int, content_type: str, content_id: int) -> str | None:
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            # 1. Check for ownership
            cursor.execute("SELECT owner_user_id FROM containers WHERE id = %s", (content_id,))
            owner_result = cursor.fetchone()
            if owner_result and owner_result['owner_user_id'] == user_id:
                return 'owner'

            # 2. Hierarchically search for permissions
            current_id = content_id
            while current_id is not None:
                cursor.execute(
                    "SELECT permission_level FROM permissions WHERE user_id = %s AND content_id = %s",
                    (user_id, current_id)
                )
                permission_result = cursor.fetchone()
                if permission_result:
                    return permission_result['permission_level']

                # Move to the parent container
                cursor.execute("SELECT parent_id FROM containers WHERE id = %s", (current_id,))
                parent_result = cursor.fetchone()
                current_id = parent_result['parent_id'] if parent_result else None
            
            return None
    except psycopg2.Error as e:
        print(f"DB Error in get_permission_level: {e}")
        return None
    finally:
        if conn:
            conn.close()

# --- Phase 3: API Auth Functions ---

def create_auth_request(request_id: str):
    """
    Inserts a new auth request with 'pending' status.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return False

        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO auth_requests (request_id, status) VALUES (%s, 'pending') ON CONFLICT (request_id) DO NOTHING",
                (request_id,)
            )
            conn.commit()
            return True
    except psycopg2.Error as e:
        print(f"DB Error in create_auth_request: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_auth_request_status(request_id: str):
    """
    Returns the status and access_token (if approved) for a given request_id.
    Returns None if not found.
    Result dict: {'status': str, 'access_token': str|None, 'user_id': int|None}
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(
                "SELECT status, access_token, user_id FROM auth_requests WHERE request_id = %s",
                (request_id,)
            )
            result = cursor.fetchone()
            if result:
                return dict(result)
            return None
    except psycopg2.Error as e:
        print(f"DB Error in get_auth_request_status: {e}")
        return None
    finally:
        if conn:
            conn.close()

def approve_auth_request(request_id: str, user_id: int, user_name: str) -> str | None:
    """
    Approves a pending auth request, generates an access token, and returns it.
    Returns None if request invalid or not found.
    """
    token = str(uuid.uuid4()) # Simple UUID token for now. In production use JWT.
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor() as cursor:
            # Update auth_requests
            cursor.execute(
                """
                UPDATE auth_requests 
                SET status = 'approved', user_id = %s, access_token = %s 
                WHERE request_id = %s AND status = 'pending'
                RETURNING request_id
                """,
                (user_id, token, request_id)
            )
            if cursor.fetchone():
                # Also create a session
                cursor.execute(
                    """
                    INSERT INTO app_sessions (user_id, access_token, device_info)
                    VALUES (%s, %s, 'Telegram Login')
                    ON CONFLICT (access_token) DO NOTHING
                    """,
                    (user_id, token)
                )
                conn.commit()
                return token
            return None # Not found or not pending
    except psycopg2.Error as e:
        print(f"DB Error in approve_auth_request: {e}")
        return None
    finally:
        if conn:
            conn.close()

def verify_access_token(token: str) -> int | None:
    """
    Checks if a token exists and is valid in app_sessions.
    Returns user_id if valid, None otherwise.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        with conn.cursor() as cursor:
            # Check app_sessions first for active sessions
            cursor.execute(
                "SELECT user_id FROM app_sessions WHERE access_token = %s AND is_active = TRUE",
                (token,)
            )
            result = cursor.fetchone()
            if result:
                return result[0]
            return None
    except psycopg2.Error as e:
        print(f"DB Error in verify_access_token: {e}")
        return None
    finally:
        if conn:
            conn.close()
