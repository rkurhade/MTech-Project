import pyodbc
from datetime import datetime, timedelta, timezone


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
            print("[INFO] Connected to SQL Server DB successfully")
            return conn
        except Exception as e:
            print(f"[ERROR] Database connection error: {e}")
            return None


class UserService:
    def __init__(self, db_config):
        self.db_config = db_config

    def store_user_data(self, user_name, email, app_name, expires_on_utc):
        conn = self.db_config.connect()
        if conn is None:
            print("[ERROR] Could not connect to DB to store user data.")
            return False

        try:
            expires_on_utc_naive = expires_on_utc.replace(tzinfo=None)  # remove tzinfo for SQL Server compatibility

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_info (user_name, email, app_name, created_date, expires_on, notified_upcoming, notified_expired)
                VALUES (?, ?, ?, SYSUTCDATETIME(), ?, 0, 0)
            """, (user_name, email, app_name, expires_on_utc_naive))

            conn.commit()
            print(f"[INFO] Stored SPN data in DB for: {app_name}")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to insert SPN data: {e}")
            return False

        finally:
            conn.close()

    def get_expired_secrets(self):
        conn = self.db_config.connect()
        if conn is None:
            print("[ERROR] Could not establish DB connection")
            return []

        try:
            cursor = conn.cursor()
            now_utc = datetime.utcnow()

            cursor.execute('''
                SELECT user_name, email, app_name, expires_on
                FROM user_info
                WHERE expires_on < ?
                AND notified_expired = 0
            ''', (now_utc,))

            return cursor.fetchall()

        except Exception as e:
            print(f"[ERROR] Failed to fetch expired secrets: {e}")
            return []

        finally:
            conn.close()

    def get_expiring_soon(self, days=30):
        conn = self.db_config.connect()
        if conn is None:
            print("[ERROR] Could not establish DB connection")
            return []

        try:
            cursor = conn.cursor()
            now_utc = datetime.utcnow()
            future_utc = now_utc + timedelta(days=days)

            cursor.execute('''
                SELECT user_name, email, app_name, expires_on
                FROM user_info
                WHERE expires_on > SYSUTCDATETIME() -- not already expired
                AND expires_on <= DATEADD(day, 30, SYSUTCDATETIME()) -- within next 30 days
                AND notified_upcoming = 0
            ''', (now_utc, future_utc))

            return cursor.fetchall()

        except Exception as e:
            print(f"[ERROR] Failed to fetch upcoming expiring secrets: {e}")
            return []

        finally:
            conn.close()

    def mark_as_notified(self, app_name, column="notified_upcoming"):
        conn = self.db_config.connect()
        if conn is None:
            print("[ERROR] Could not connect to DB to update notified flag.")
            return

        try:
            cursor = conn.cursor()
            if column not in ["notified_upcoming", "notified_expired"]:
                print(f"[ERROR] Invalid column name: {column}")
                return

            cursor.execute(f"""
                UPDATE user_info
                SET {column} = 1
                WHERE app_name = ?
            """, (app_name,))
            conn.commit()
            print(f"[INFO] Marked '{app_name}' as {column} = 1.")

        except Exception as e:
            print(f"[ERROR] Failed to update {column} flag for {app_name}: {e}")

        finally:
            conn.close()