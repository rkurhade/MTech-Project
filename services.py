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

    def _execute_query(self, query, params=None, fetch_type='none'):
        """
        Common database execution helper.
        fetch_type: 'none', 'one', 'all', 'dict_list'
        """
        conn = self.db_config.connect()
        if not conn:
            print("[ERROR] Could not connect to database.")
            return None
        
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            
            if fetch_type == 'one':
                return cursor.fetchone()
            elif fetch_type == 'all':
                return cursor.fetchall()
            elif fetch_type == 'dict_list':
                results = cursor.fetchall()
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in results]
            else:  # 'none' - for INSERT/UPDATE
                conn.commit()
                return True
                
        except Exception as e:
            print(f"[ERROR] Database query failed: {e}")
            return None
        finally:
            conn.close()

    def _get_user_info_id(self, app_name):
        """Get user_info_id for an app_name."""
        result = self._execute_query(
            "SELECT TOP 1 id FROM user_info WHERE app_name = ? ORDER BY created_date DESC",
            (app_name,),
            'one'
        )
        return result[0] if result else None

    def get_user_info_by_id(self, user_info_id):
        """Get user details by user_info_id."""
        result = self._execute_query(
            "SELECT user_name, email FROM user_info WHERE id = ?",
            (user_info_id,),
            'one'
        )
        return {'user_name': result[0], 'email': result[1]} if result else None

    def store_user_and_secret(self, user_name, email, app_name, secret_info):
        """
        Inserts user into user_info and secret into app_secrets.
        secret_info: dict with keys key_id, end_date, display_name.
        Returns True if both inserts succeed.
        """
        # Insert user_info
        user_success = self._execute_query("""
            INSERT INTO user_info (user_name, email, app_name, created_date)
            VALUES (?, ?, ?, GETDATE())
        """, (user_name, email, app_name))
        
        if not user_success:
            return False
        
        # Get user_info_id
        user_info_id = self._get_user_info_id(app_name)
        if not user_info_id:
            return False
        
        # Insert app_secrets - Set notified_renewal = 1 for initial secrets to prevent duplicate emails
        return self._execute_query("""
            INSERT INTO app_secrets (
                app_name, key_id, end_date, created_date, display_name,
                notified_upcoming, notified_expired, notified_renewal,
                last_updated_at, user_info_id
            ) VALUES (?, ?, ?, GETDATE(), ?, 0, 0, 1, GETDATE(), ?)
        """, (
            app_name,
            secret_info['key_id'],
            secret_info['end_date'],
            secret_info['display_name'],
            user_info_id
        ))

    def add_new_secret(self, app_name, secret_info):
        """
        Adds a new secret for an app.
        secret_info: dict with keys key_id, end_date, display_name.
        """
        user_info_id = self._get_user_info_id(app_name)
        if not user_info_id:
            print(f"[ERROR] Could not find user_info_id for app: {app_name}")
            return False
        
        return self._execute_query("""
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

    def get_latest_secret(self, app_name):
        """
        Gets the most recent secret for an application based on created_date.
        """
        results = self._execute_query("""
            SELECT TOP 1 id, app_name, key_id, end_date, created_date, display_name,
                   notified_upcoming, notified_expired, notified_renewal, last_updated_at, user_info_id
            FROM app_secrets
            WHERE app_name = ?
            ORDER BY created_date DESC
        """, (app_name,), 'dict_list')
        
        return results[0] if results else None

    def update_secret_expiry(self, secret_id, new_end_date):
        """
        Updates expiry date for a secret.
        """
        return self._execute_query(
            "UPDATE app_secrets SET end_date = ?, last_updated_at = GETDATE() WHERE id = ?",
            (new_end_date, secret_id)
        )

    def mark_secret_notified(self, secret_id, column="notified_upcoming"):
        """
        Marks a secret as notified for a given column.
        """
        if column not in ["notified_upcoming", "notified_expired", "notified_renewal"]:
            print(f"[ERROR] Invalid column name: {column}")
            return False
        
        success = self._execute_query(f"""
            UPDATE app_secrets
            SET {column} = 1, last_updated_at = GETDATE()
            WHERE id = ?
        """, (secret_id,))
        
        if success:
            print(f"[DEBUG] Marked secret {secret_id} as notified for {column}")
        return success

    def get_expiring_secrets(self, days=30, resend_interval_days=2):
        """
        Returns secrets expiring in next 'days' days.
        Only returns secrets that haven't been notified or last notification was sent more than resend_interval_days ago.
        """
        now = datetime.now()
        future = now + timedelta(days=days)
        
        query = '''
            SELECT id, app_name, key_id, end_date, created_date, display_name,
                   notified_upcoming, notified_expired, notified_renewal, last_updated_at, user_info_id
            FROM app_secrets
            WHERE end_date BETWEEN ? AND ?
            AND (
                notified_upcoming = 0 
                OR (
                    notified_upcoming = 1 
                    AND DATEDIFF(day, last_updated_at, GETDATE()) >= ?
                )
            )
        '''
        
        results = self._execute_query(query, (now, future, resend_interval_days), 'dict_list')
        print(f"[DEBUG] Found {len(results)} expiring secrets (between {now} and {future}, resend interval: {resend_interval_days} days)")
        return results

    def get_expired_secrets(self, resend_interval_days=2):
        """
        Returns secrets that have expired.
        Only returns secrets that haven't been notified for expiry or last notification was sent more than resend_interval_days ago.
        """
        now = datetime.now()
        
        query = '''
            SELECT id, app_name, key_id, end_date, created_date, display_name,
                   notified_upcoming, notified_expired, notified_renewal, last_updated_at, user_info_id
            FROM app_secrets
            WHERE end_date < ?
            AND (
                notified_expired = 0 
                OR (
                    notified_expired = 1 
                    AND DATEDIFF(day, last_updated_at, GETDATE()) >= ?
                )
            )
        '''
        
        results = self._execute_query(query, (now, resend_interval_days), 'dict_list')
        print(f"[DEBUG] Found {len(results)} expired secrets (before {now}, resend interval: {resend_interval_days} days)")
        return results

    def get_all_applications(self):
        """Fetches all applications to check their secret expiry status."""
        return self._execute_query("""
            SELECT id, user_name, email, app_name, created_date
            FROM user_info
        """, fetch_type='dict_list') or []

    def get_monthly_report_data(self, year, month):
        """
        Gets Service Principal creation report for a specific month/year.
        Returns statistics and detailed list of created SPNs.
        """
        print(f"[DEBUG] Generating monthly report for year={year}, month={month}")
        
        # Get summary statistics
        summary_row = self._execute_query("""
            SELECT 
                COUNT(*) as total_created,
                COUNT(DISTINCT user_name) as unique_users,
                COUNT(DISTINCT email) as unique_emails
            FROM user_info 
            WHERE YEAR(created_date) = ? AND MONTH(created_date) = ?
        """, (year, month), 'one')
        
        if not summary_row:
            return None
            
        summary = {
            'total_created': summary_row[0],
            'unique_users': summary_row[1],
            'unique_emails': summary_row[2],
            'year': year,
            'month': month
        }
        print(f"[DEBUG] Summary data: {summary}")
        
        # Get detailed list of created SPNs
        details = self._execute_query("""
            SELECT 
                user_name, 
                email, 
                app_name, 
                created_date,
                DAY(created_date) as day_of_month
            FROM user_info 
            WHERE YEAR(created_date) = ? AND MONTH(created_date) = ?
            ORDER BY created_date DESC
        """, (year, month), 'dict_list') or []
        
        print(f"[DEBUG] Found {len(details)} detailed records")
        
        return {
            'summary': summary,
            'details': details
        }

    def get_current_month_report(self):
        """
        Gets Service Principal creation report for the current month.
        """
        now = datetime.now()
        return self.get_monthly_report_data(now.year, now.month)

    def get_previous_month_report(self):
        """
        Gets Service Principal creation report for the previous month.
        """
        now = datetime.now()
        # Handle year rollover
        if now.month == 1:
            prev_year = now.year - 1
            prev_month = 12
        else:
            prev_year = now.year
            prev_month = now.month - 1
            
        return self.get_monthly_report_data(prev_year, prev_month)

    def test_database_connection(self):
        """
        Test database connection and basic queries for debugging.
        """
        print("[DEBUG] Testing database connection...")
        
        # Test basic queries
        user_count = self._execute_query("SELECT COUNT(*) FROM user_info", fetch_type='one')
        if not user_count:
            print("[ERROR] Database connection failed!")
            return False
        
        secrets_count = self._execute_query("SELECT COUNT(*) FROM app_secrets", fetch_type='one')
        
        print(f"[DEBUG] Total records in user_info: {user_count[0]}")
        print(f"[DEBUG] Total records in app_secrets: {secrets_count[0] if secrets_count else 0}")
        
        # Show all unique app names in user_info
        user_apps = self._execute_query(
            "SELECT DISTINCT app_name, created_date FROM user_info ORDER BY created_date DESC",
            fetch_type='all'
        )
        print(f"[DEBUG] Apps in user_info table:")
        for app in user_apps or []:
            print(f"[DEBUG] - {app[0]} (created: {app[1]})")
        
        # Show all unique app names in app_secrets
        secret_apps = self._execute_query(
            "SELECT DISTINCT app_name, MIN(created_date) as first_created FROM app_secrets GROUP BY app_name ORDER BY first_created DESC",
            fetch_type='all'
        )
        print(f"[DEBUG] Apps in app_secrets table:")
        for app in secret_apps or []:
            print(f"[DEBUG] - {app[0]} (first secret: {app[1]})")
        
        # Test recent records
        recent = self._execute_query(
            "SELECT TOP 5 user_name, email, app_name, created_date FROM user_info ORDER BY created_date DESC",
            fetch_type='all'
        )
        print(f"[DEBUG] Recent user_info records: {len(recent or [])} found")
        for record in recent or []:
            print(f"[DEBUG] Record: {record}")
        
        return True