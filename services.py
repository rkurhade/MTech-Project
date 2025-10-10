# services.py
import pyodbc
from datetime import datetime, timedelta
import pytz

class DatabaseConfig:
    def __init__(self, config):
        self.server = config['server']
        self.database = config['database']
        self.username = config['username']
        self.password = config['password']

    def validate(self):
        if not all([self.server, self.database, self.username, self.password]):
            raise ValueError("Missing or incomplete database configuration.")

    def connect(self):
        try:
            conn = pyodbc.connect(
                'DRIVER={ODBC Driver 17 for SQL Server};'
                f'SERVER={self.server};'
                f'DATABASE={self.database};'
                f'UID={self.username};'
                f'PWD={self.password}'
            )
            return conn
        except Exception as e:
            print(f"[ERROR] Database connection error: {e}")
            return None


class UserService:
    def __init__(self, db_config):
        self.db_config = db_config

    def store_user_data(self, user_name, email, app_name, expires_on_utc):
        conn = self.db_config.connect()
        if not conn:
            print("[ERROR] Could not connect to DB to store user data.")
            return False

        try:
            ist_tz = pytz.timezone("Asia/Kolkata")
            expires_on_ist = expires_on_utc.astimezone(ist_tz).replace(tzinfo=None)

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_info (
                    user_name, email, app_name, created_date, expires_on,
                    notified_upcoming, notified_expired, last_notified_at
                )
                VALUES (?, ?, ?, GETDATE(), ?, 0, 0, NULL)
            """, (user_name, email, app_name, expires_on_ist))

            conn.commit()
            return True

        except Exception as e:
            print(f"[ERROR] Failed to insert SPN data: {e}")
            return False

        finally:
            conn.close()

    # NEW: Fetches all applications for the notification check
    def get_all_applications(self):
        """Fetches all applications to check their secret expiry status."""
        conn = self.db_config.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_name, email, app_name, last_notified_at
                FROM user_info
            """)
            # Convert rows to a list of dictionaries for easier access
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[ERROR] Failed to fetch all applications: {e}")
            return []
        finally:
            conn.close()

    # NEW: Updates the expiry date and resets notification flags for an app
    def update_application_expiry(self, app_id, new_expiry_date_utc):
        """Updates the expiry date and resets notification flags for an app."""
        conn = self.db_config.connect()
        if not conn:
            return False
        try:
            ist_tz = pytz.timezone("Asia/Kolkata")
            new_expiry_ist = new_expiry_date_utc.astimezone(ist_tz).replace(tzinfo=None)

            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_info
                SET expires_on = ?, notified_upcoming = 0, notified_expired = 0, last_notified_at = NULL
                WHERE id = ?
            """, (new_expiry_ist, app_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to update expiry for app_id {app_id}: {e}")
            return False
        finally:
            conn.close()

    # UPDATED: Now uses app_id instead of app_name for reliability
    def mark_as_notified(self, app_id, column="notified_upcoming"):
        conn = self.db_config.connect()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            if column not in ["notified_upcoming", "notified_expired"]:
                print(f"[ERROR] Invalid column name: {column}")
                return

            cursor.execute(f"""
                UPDATE user_info
                SET {column} = 1, last_notified_at = GETDATE()
                WHERE id = ?
            """, (app_id,))
            conn.commit()
        
        except Exception as e:
            print(f"[ERROR] Failed to update {column} flag for app_id {app_id}: {e}")
        
        finally:
            conn.close()

    # NOTE: The get_expiring_soon and get_expired_secrets methods are no longer used
    # by the main notification logic but are kept here in case they are used elsewhere.
    def get_expiring_soon(self, days=30):
        conn = self.db_config.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            now = datetime.now()
            future = now + timedelta(days=days)

            cursor.execute('''
                SELECT user_name, email, app_name, expires_on, last_notified_at
                FROM user_info
                WHERE expires_on BETWEEN ? AND ?
                AND (notified_upcoming = 0 OR last_notified_at <= DATEADD(day, -3, GETDATE()) OR last_notified_at IS NULL)
            ''', (now, future))

            return cursor.fetchall()

        except Exception as e:
            print(f"[ERROR] Failed to fetch upcoming expiring secrets: {e}")
            return []

        finally:
            conn.close()

    def get_expired_secrets(self):
        conn = self.db_config.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            now = datetime.now()

            cursor.execute('''
                SELECT user_name, email, app_name, expires_on, last_notified_at
                FROM user_info
                WHERE expires_on < ?
                AND (notified_expired = 0 OR last_notified_at <= DATEADD(day, -3, GETDATE()) OR last_notified_at IS NULL)
            ''', (now,))

            return cursor.fetchall()

        except Exception as e:
            print(f"[ERROR] Failed to fetch expired secrets: {e}")
            return []

        finally:
            conn.close()