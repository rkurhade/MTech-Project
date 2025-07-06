import pyodbc
from datetime import datetime

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
            print("[INFO] Connected to DB successfully")
            return conn
        except pyodbc.Error as e:
            print(f"[ERROR] Database connection error: {e}")
            return None


class UserService:
    def __init__(self, db_config):
        self.db_config = db_config

    def store_user_data(self, user_name, email, app_name, expires_on):
        conn = self.db_config.connect()
        if conn is None:
            print("[ERROR] Could not establish DB connection")
            return False

        try:
            cursor = conn.cursor()
            created_at = datetime.utcnow()

            print(f"[DEBUG] Inserting into DB: {user_name}, {email}, {app_name}, {expires_on}, {created_at}")

            cursor.execute('''
                INSERT INTO user_info (user_name, email, app_name, expires_on, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_name, email, app_name, expires_on, created_at))

            conn.commit()
            print("[INFO] DB commit successful")
            return True

        except Exception as e:
            print(f"[ERROR] Failed to store user data: {e}")
            return False

        finally:
            conn.close()
            print("[INFO] DB connection closed")