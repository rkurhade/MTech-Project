import pyodbc

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
        except pyodbc.Error as e:
            print(f"Database connection error: {e}")
            return None


class UserService:
    def __init__(self, db_config):
        self.db_config = db_config

    def store_user_data(self, user_name, email, app_name, expires_on):
        conn = self.db_config.connect()
        if conn is None:
            return False

        try:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO user_info (user_name, email, app_name, expires_on)
                VALUES (?, ?, ?, ?)
            ''', (user_name, email, app_name, expires_on))

            return True
        except Exception as e:
            print(f"Error storing user data: {e}")
            return False
        finally:
            conn.close()