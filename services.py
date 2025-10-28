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

    def get_latest_secret(self, app_name):
        """
        Gets the most recent secret for an application based on created_date.
        """
        conn = self.db_config.connect()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 1 id, app_name, key_id, end_date, created_date, display_name,
                       notified_upcoming, notified_expired, notified_renewal, last_updated_at, user_info_id
                FROM app_secrets
                WHERE app_name = ?
                ORDER BY created_date DESC
            """, (app_name,))
            row = cursor.fetchone()
            if row:
                columns = [column[0] for column in cursor.description]
                return dict(zip(columns, row))
            return None
        except Exception as e:
            print(f"[ERROR] Failed to get latest secret: {e}")
            return None
        finally:
            conn.close()

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
                SET {column} = 1, last_updated_at = GETDATE()
                WHERE id = ?
            """, (secret_id,))
            conn.commit()
            print(f"[DEBUG] Marked secret {secret_id} as notified for {column}")
        except Exception as e:
            print(f"[ERROR] Failed to update {column} flag for secret_id {secret_id}: {e}")
        finally:
            conn.close()

    def get_expiring_secrets(self, days=30, resend_interval_days=2):
        """
        Returns secrets expiring in next 'days' days.
        Only returns secrets that haven't been notified or last notification was sent more than resend_interval_days ago.
        """
        conn = self.db_config.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            now = datetime.now()
            future = now + timedelta(days=days)
            cursor.execute('''
                SELECT id, app_name, key_id, end_date, created_date, display_name,
                       notified_upcoming, notified_expired, notified_renewal, last_updated_at, user_info_id
                FROM app_secrets
                WHERE end_date BETWEEN ? AND ?
                AND (notified_upcoming = 0 OR 
                     (notified_upcoming = 1 AND last_updated_at <= DATEADD(day, -?, GETDATE())))
            ''', (now, future, resend_interval_days))
            results = cursor.fetchall()
            print(f"[DEBUG] Found {len(results)} expiring secrets (between {now} and {future}, resend interval: {resend_interval_days} days)")
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in results]
        except Exception as e:
            print(f"[ERROR] Failed to fetch expiring secrets: {e}")
            return []
        finally:
            conn.close()

    def get_expired_secrets(self, resend_interval_days=2):
        """
        Returns secrets that have expired.
        Only returns secrets that haven't been notified for expiry or last notification was sent more than resend_interval_days ago.
        """
        conn = self.db_config.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute('''
                SELECT id, app_name, key_id, end_date, created_date, display_name,
                       notified_upcoming, notified_expired, notified_renewal, last_updated_at, user_info_id
                FROM app_secrets
                WHERE end_date < ?
                AND (notified_expired = 0 OR 
                     (notified_expired = 1 AND last_updated_at <= DATEADD(day, -?, GETDATE())))
            ''', (now, resend_interval_days))
            results = cursor.fetchall()
            print(f"[DEBUG] Found {len(results)} expired secrets (before {now}, resend interval: {resend_interval_days} days)")
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in results]
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
                SELECT id, user_name, email, app_name, created_date
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

    def get_monthly_report_data(self, year, month, include_all_apps=False):
        """
        Gets Service Principal creation report for a specific month/year.
        
        Args:
            year: Report year
            month: Report month
            include_all_apps: If True, includes all apps from app_secrets table
                            If False, only includes apps created via Flask app (user_info table)
        
        Returns statistics and detailed list of created SPNs.
        """
        print(f"[DEBUG] Generating monthly report for year={year}, month={month}, include_all_apps={include_all_apps}")
        conn = self.db_config.connect()
        if not conn:
            print("[ERROR] Database connection failed in get_monthly_report_data")
            return None

        try:
            cursor = conn.cursor()
            
            if include_all_apps:
                # Get summary statistics from app_secrets (includes all apps)
                cursor.execute("""
                    SELECT 
                        COUNT(DISTINCT app_name) as total_created,
                        COUNT(DISTINCT ISNULL(ui.user_name, 'Unknown')) as unique_users,
                        COUNT(DISTINCT ISNULL(ui.email, 'Unknown')) as unique_emails
                    FROM app_secrets s
                    LEFT JOIN user_info ui ON s.user_info_id = ui.id
                    WHERE YEAR(s.created_date) = ? AND MONTH(s.created_date) = ?
                """, (year, month))
                
                summary_row = cursor.fetchone()
                summary = {
                    'total_created': summary_row[0] if summary_row else 0,
                    'unique_users': summary_row[1] if summary_row else 0,
                    'unique_emails': summary_row[2] if summary_row else 0,
                    'year': year,
                    'month': month,
                    'report_type': 'All Applications (including manual/external)'
                }
                
                # Get detailed list from app_secrets
                cursor.execute("""
                    SELECT 
                        ISNULL(ui.user_name, 'Unknown') as user_name,
                        ISNULL(ui.email, 'Unknown') as email,
                        s.app_name,
                        s.created_date,
                        DAY(s.created_date) as day_of_month,
                        s.display_name
                    FROM app_secrets s
                    LEFT JOIN user_info ui ON s.user_info_id = ui.id
                    WHERE YEAR(s.created_date) = ? AND MONTH(s.created_date) = ?
                    ORDER BY s.created_date DESC
                """, (year, month))
            else:
                # Get summary statistics from user_info (Flask app created only)
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_created,
                        COUNT(DISTINCT user_name) as unique_users,
                        COUNT(DISTINCT email) as unique_emails
                    FROM user_info 
                    WHERE YEAR(created_date) = ? AND MONTH(created_date) = ?
                """, (year, month))
                
                summary_row = cursor.fetchone()
                summary = {
                    'total_created': summary_row[0] if summary_row else 0,
                    'unique_users': summary_row[1] if summary_row else 0,
                    'unique_emails': summary_row[2] if summary_row else 0,
                    'year': year,
                    'month': month,
                    'report_type': 'Flask App Created Only'
                }
                
                # Get detailed list from user_info
                cursor.execute("""
                    SELECT 
                        user_name, 
                        email, 
                        app_name, 
                        created_date,
                        DAY(created_date) as day_of_month
                    FROM user_info 
                    WHERE YEAR(created_date) = ? AND MONTH(created_date) = ?
                    ORDER BY created_date DESC
                """, (year, month))
            
            print(f"[DEBUG] Summary data: {summary}")
            
            columns = [column[0] for column in cursor.description]
            details = [dict(zip(columns, row)) for row in cursor.fetchall()]
            print(f"[DEBUG] Found {len(details)} detailed records")
            
            return {
                'summary': summary,
                'details': details
            }
            
        except Exception as e:
            print(f"[ERROR] Failed to fetch monthly report data: {e}")
            return None
        finally:
            conn.close()

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
        conn = self.db_config.connect()
        if not conn:
            print("[ERROR] Database connection failed!")
            return False
        
        try:
            cursor = conn.cursor()
            # Test basic query
            cursor.execute("SELECT COUNT(*) FROM user_info")
            count = cursor.fetchone()[0]
            print(f"[DEBUG] Total records in user_info: {count}")
            
            # Test app_secrets table
            cursor.execute("SELECT COUNT(*) FROM app_secrets")
            secrets_count = cursor.fetchone()[0]
            print(f"[DEBUG] Total records in app_secrets: {secrets_count}")
            
            # Show all unique app names in user_info
            cursor.execute("SELECT DISTINCT app_name, created_date FROM user_info ORDER BY created_date DESC")
            user_apps = cursor.fetchall()
            print(f"[DEBUG] Apps in user_info table:")
            for app in user_apps:
                print(f"[DEBUG] - {app[0]} (created: {app[1]})")
            
            # Show all unique app names in app_secrets
            cursor.execute("SELECT DISTINCT app_name, MIN(created_date) as first_created FROM app_secrets GROUP BY app_name ORDER BY first_created DESC")
            secret_apps = cursor.fetchall()
            print(f"[DEBUG] Apps in app_secrets table:")
            for app in secret_apps:
                print(f"[DEBUG] - {app[0]} (first secret: {app[1]})")
            
            # Test date-based query
            cursor.execute("SELECT TOP 5 user_name, email, app_name, created_date FROM user_info ORDER BY created_date DESC")
            recent = cursor.fetchall()
            print(f"[DEBUG] Recent user_info records: {len(recent)} found")
            for record in recent:
                print(f"[DEBUG] Record: {record}")
            
            return True
        except Exception as e:
            print(f"[ERROR] Database test failed: {e}")
            return False
        finally:
            conn.close()