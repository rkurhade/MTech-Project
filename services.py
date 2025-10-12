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

    def store_user_and_secret(self, user_name, email, app_name, secret_info):
        """
        Inserts user into user_info and secret into app_secrets.
        secret_info: dict with keys key_id, end_date, display_name.
        Returns True if both inserts succeed.
        """
        conn = self.db_config.connect()
        if not conn:
            print("[ERROR] Could not connect to DB to store user and secret.")
            return False
        try:
            cursor = conn.cursor()
            # Insert user_info
            cursor.execute("""
                INSERT INTO user_info (user_name, email, app_name, created_date)
                VALUES (?, ?, ?, GETDATE())
            """, (user_name, email, app_name))
            conn.commit()
            # Get user_info_id
            cursor.execute("SELECT TOP 1 id FROM user_info WHERE app_name = ? ORDER BY created_date DESC", (app_name,))
            user_info_id = cursor.fetchone()[0]
            # Insert app_secrets
            cursor.execute("""
                INSERT INTO app_secrets (
                    app_name, key_id, end_date, created_date, display_name,
                    notified_upcoming, notified_expired, notified_renewal,
                    last_updated_at, user_info_id
                ) VALUES (?, ?, ?, GETDATE(), ?, 0, 0, 0, GETDATE(), ?)
            """, (
                app_name,
                secret_info['key_id'],
                secret_info['end_date'],
                secret_info['display_name'],
                user_info_id
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to insert user or secret: {e}")
            return False
        finally:
            conn.close()

    def add_new_secret(self, app_name, secret_info):
        """
        Adds a new secret for an app.
        secret_info: dict with keys key_id, end_date, display_name.
        """
        conn = self.db_config.connect()
        if not conn:
            print("[ERROR] Could not connect to DB to add new secret.")
            return False
        try:
            cursor = conn.cursor()
            # Get user_info_id
            cursor.execute("SELECT TOP 1 id FROM user_info WHERE app_name = ? ORDER BY created_date DESC", (app_name,))
            user_info_id = cursor.fetchone()[0]
            # Insert new secret
            cursor.execute("""
                INSERT INTO app_secrets (
                    app_name, key_id, end_date, created_date, display_name,
                    notified_upcoming, notified_expired, notified_renewal,
                    last_updated_at, user_info_id
                ) VALUES (?, ?, ?, GETDATE(), ?, 0, 0, 0, GETDATE(), ?)
            """, (
                app_name,
                secret_info['key_id'],
                secret_info['end_date'],
                secret_info['display_name'],
                user_info_id
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to add new secret: {e}")
            return False
        finally:
            conn.close()

    # REMOVED: get_latest_secret (no latest column in schema)

    def update_secret_expiry(self, secret_id, new_end_date):
        """
        Updates expiry date for a secret.
        """
        conn = self.db_config.connect()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE app_secrets SET end_date = ?, last_updated_at = GETDATE() WHERE id = ?", (new_end_date, secret_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to update secret expiry: {e}")
            return False
        finally:
            conn.close()

    def mark_secret_notified(self, secret_id, column="notified_upcoming"):
        """
        Marks a secret as notified for a given column.
        """
        conn = self.db_config.connect()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            if column not in ["notified_upcoming", "notified_expired", "notified_renewal"]:
                print(f"[ERROR] Invalid column name: {column}")
                return
            cursor.execute(f"""
                UPDATE app_secrets
                SET {column} = 1, last_notified_at = GETDATE()
                WHERE id = ?
            """, (secret_id,))
            conn.commit()
        except Exception as e:
            print(f"[ERROR] Failed to update {column} flag for secret_id {secret_id}: {e}")
        finally:
            conn.close()

    def get_expiring_secrets(self, days=30):
        """
        Returns secrets expiring in next 'days' days.
        """
        conn = self.db_config.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            now = datetime.now()
            future = now + timedelta(days=days)
            cursor.execute('''
                SELECT * FROM app_secrets
                WHERE end_date BETWEEN ? AND ?
                AND (notified_upcoming = 0 OR last_notified_at <= DATEADD(day, -3, GETDATE()) OR last_notified_at IS NULL)
            ''', (now, future))
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[ERROR] Failed to fetch expiring secrets: {e}")
            return []
        finally:
            conn.close()

    def get_expired_secrets(self):
        """
        Returns secrets that have expired.
        """
        conn = self.db_config.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('''
                SELECT * FROM app_secrets
                WHERE end_date < ?
                AND (notified_expired = 0 OR last_notified_at <= DATEADD(day, -3, GETDATE()) OR last_notified_at IS NULL)
            ''', (now,))
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[ERROR] Failed to fetch expired secrets: {e}")
            return []
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
