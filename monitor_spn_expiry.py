import pyodbc
from datetime import datetime, timedelta, timezone
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# === Load .env file for local testing ===
# Environment variables expected:
# DB_SERVER, DB_DATABASE, DB_USERNAME, DB_PASSWORD
# MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD
load_dotenv()

# === Database Configuration ===
class DatabaseConfig:
    """Handles database connection configuration and instantiation."""
    def __init__(self, config):
        self.server = config.get('server')
        self.database = config.get('database')
        self.username = config.get('username')
        self.password = config.get('password')

    def validate(self):
        """Raises ValueError if any essential DB config is missing."""
        if not all([self.server, self.database, self.username, self.password]):
            raise ValueError("Missing essential DB configuration (server, database, username, or password).")

    def connect(self):
        """Establishes a pyodbc connection to SQL Server."""
        try:
            # Use SQL Server ODBC Driver 17 - adjust driver name if necessary
            conn = pyodbc.connect(
                'DRIVER={ODBC Driver 17 for SQL Server};'
                f'SERVER={self.server};DATABASE={self.database};'
                f'UID={self.username};PWD={self.password}'
            )
            return conn
        except Exception as e:
            print(f"[ERROR] DB connection error. Please check configuration and driver installation: {e}")
            return None

# === User Service (Data Access Layer) ===
class UserService:
    """Manages interactions with the database to fetch and update secret status."""
    def __init__(self, db_config):
        self.db_config = db_config

    def _execute_query(self, sql, params=None, fetch=True):
        """Helper function to execute SQL queries."""
        conn = self.db_config.connect()
        if not conn:
            return [] if fetch else None

        try:
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            if fetch:
                rows = cursor.fetchall()
                # Assuming row format: id, user_name, email, app_name, client_id, expires_on, ...
                return rows
            else:
                conn.commit()
                return True
        except Exception as e:
            print(f"[ERROR] SQL execution failed: {e}. Query: {sql[:50]}...")
            return [] if fetch else False
        finally:
            if conn:
                conn.close()

    def get_expiring_soon(self, days=30, repeat_interval=2):
        """
        Fetches secrets expiring in the next 'days' (30) that require notification.
        Includes secrets that have never been notified OR were notified more than
        'repeat_interval' (2) days ago.
        """
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=days)

        sql = '''
            SELECT id, user_name, email, app_name, client_id, expires_on, notified_upcoming, last_notified_at
            FROM user_info
            WHERE expires_on BETWEEN ? AND ?
            AND (
                notified_upcoming = 0
                OR last_notified_at IS NULL
                OR last_notified_at <= DATEADD(day, -?, GETDATE()) -- Repeat notification logic
            )
        '''
        # Note: The database is assumed to handle the timezone conversion/comparison internally for GETDATE()
        rows = self._execute_query(sql, (now, future, repeat_interval))
        print(f"[DEBUG] Found {len(rows)} secrets expiring soon.")
        return rows

    def get_expired_secrets(self, repeat_interval=2):
        """
        Fetches secrets that have already expired and need repeated notification.
        Notifies if never notified as expired OR if notified more than 'repeat_interval' (2) days ago.
        """
        now = datetime.now(timezone.utc)
        
        sql = '''
            SELECT id, user_name, email, app_name, client_id, expires_on, notified_expired, last_notified_at
            FROM user_info
            WHERE expires_on < ?
            AND (
                notified_expired = 0
                OR last_notified_at IS NULL
                OR last_notified_at <= DATEADD(day, -?, GETDATE()) -- Repeat notification logic
            )
        '''
        rows = self._execute_query(sql, (now, repeat_interval))
        print(f"[DEBUG] Found {len(rows)} expired secrets requiring notification.")
        return rows

    def get_renewed_secrets(self):
        """
        Fetches secrets that were previously expired but have now been updated
        (new 'expires_on' in the future) and haven't been confirmed as renewed.
        """
        now = datetime.now(timezone.utc)
        
        sql = '''
            SELECT id, user_name, email, app_name, client_id, expires_on, notified_expired, notified_renewal
            FROM user_info
            WHERE expires_on >= ?             -- Secret is now valid (renewed)
            AND notified_expired = 1          -- AND Was previously marked as expired
            AND (notified_renewal = 0 OR notified_renewal IS NULL) -- AND Hasn't received renewal confirmation
        '''
        rows = self._execute_query(sql, (now,))
        print(f"[DEBUG] Found {len(rows)} renewed secrets requiring confirmation.")
        return rows

    def mark_as_notified(self, secret_id, column):
        """Updates the specified notification flag and the last_notified_at timestamp."""
        # Ensure the column name is safe for direct injection (only uses predefined column names)
        if column not in ["notified_upcoming", "notified_expired", "notified_renewal"]:
            raise ValueError(f"Invalid column name: {column}")

        sql = f'''
            UPDATE user_info
            SET {column} = 1, last_notified_at = GETDATE()
            WHERE id = ?
        '''
        return self._execute_query(sql, (secret_id,), fetch=False)

# === Email Setup ===
smtp_server = os.getenv("MAIL_SERVER", "smtp.gmail.com")
smtp_port = int(os.getenv("MAIL_PORT", 587))
smtp_user = os.getenv("MAIL_USERNAME")
smtp_pass = os.getenv("MAIL_PASSWORD")
sender_email = os.getenv("MAIL_DEFAULT_SENDER", smtp_user)

def send_email(to_email, subject, body_html):
    """Sends an HTML formatted email using SMTP configuration from environment variables."""
    if not all([smtp_user, smtp_pass, to_email]):
        print(f"[WARN] Skipping email to {to_email}. SMTP credentials/recipient missing.")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))

        print(f"[INFO] Attempting to send email to {to_email} — {subject}")
        with smtplib.SMTP(smtp_server, smtp_port) as server_conn:
            server_conn.starttls()
            server_conn.login(smtp_user, smtp_pass)
            server_conn.send_message(msg)
        print(f"[INFO] Successfully sent email to {to_email}.")

    except Exception as e:
        print(f"[ERROR] Failed to send email to {to_email} using {smtp_server}:{smtp_port}: {e}")

# === Email Templates ===
def expiring_email(user_name, app_name, client_id, expiry):
    return f"""
    <p>Hi {user_name},</p>
    <p><b>ACTION REQUIRED:</b> Your Service Principal secret (Client ID starting with <b>{client_id[:8]}...</b>) for <b>{app_name}</b> is expiring soon on <b>{expiry.strftime('%Y-%m-%d')}</b>. You have less than 30 days remaining.</p>
    <p>Please log into the portal to renew this secret before its expiration to avoid service interruption.</p>
    <p>Thank you,<br>SPN Secret Management Team</p>
    """

def expired_email(user_name, app_name, client_id, expiry):
    return f"""
    <p>Hi {user_name},</p>
    <p><b>URGENT ACTION REQUIRED:</b> Your Service Principal secret (Client ID starting with <b>{client_id[:8]}...</b>) for <b>{app_name}</b> expired on <b>{expiry.strftime('%Y-%m-%d')}</b>.</p>
    <p>Please generate a new secret immediately through the portal. This secret is no longer valid and may cause authentication failures.</p>
    <p>Thank you,<br>SPN Secret Management Team</p>
    """

def renewal_email(user_name, app_name, client_id, expiry):
    return f"""
    <p>Hi {user_name},</p>
    <p><b>CONFIRMATION:</b> Your Service Principal secret (Client ID starting with <b>{client_id[:8]}...</b>) for <b>{app_name}</b> has been successfully renewed.</p>
    <p>The new expiration date is <b>{expiry.strftime('%Y-%m-%d')}</b> (assuming a 2-year renewal). No further action is required for this secret at this time.</p>
    <p>Thank you,<br>SPN Secret Management Team</p>
    """

# === Main Function (Scheduled Runner) ===
def main():
    """Main execution function to perform all monitoring and notification tasks."""
    try:
        db_config = DatabaseConfig({
            "server": os.getenv("DB_SERVER"),
            "database": os.getenv("DB_DATABASE"),
            "username": os.getenv("DB_USERNAME"),
            "password": os.getenv("DB_PASSWORD")
        })
        db_config.validate()
    except ValueError as e:
        print(f"[FATAL] Initialization failed: {e}")
        return

    user_service = UserService(db_config)

    print("--- Starting Secret Monitoring Check ---")

    # 1. Check for Expiring Soon (30 days window, repeat every 2 days)
    for s in user_service.get_expiring_soon(days=30, repeat_interval=2):
        # s is a pyodbc Row object/tuple
        secret_id, user_name, email, app_name, client_id, expires_on, _, _ = s
        send_email(
            email, 
            f"[ACTION REQUIRED] SP Secret Expiring Soon: {app_name}", 
            expiring_email(user_name, app_name, client_id, expires_on)
        )
        # Mark as notified for 'upcoming' to stop repeated initial 30-day emails unless 2 days have passed.
        user_service.mark_as_notified(secret_id, "notified_upcoming")

    # 2. Check for Expired Secrets (Repeat every 2 days until renewal)
    for s in user_service.get_expired_secrets(repeat_interval=2):
        secret_id, user_name, email, app_name, client_id, expires_on, _, _ = s
        send_email(
            email, 
            f"[URGENT] SP Secret Expired: {app_name}", 
            expired_email(user_name, app_name, client_id, expires_on)
        )
        # Mark as notified for 'expired' to track the start of the expired notification loop.
        user_service.mark_as_notified(secret_id, "notified_expired")

    # 3. Check for Renewed Secrets (Confirmation mail)
    for s in user_service.get_renewed_secrets():
        secret_id, user_name, email, app_name, client_id, expires_on, _, _ = s
        send_email(
            email, 
            f"[CONFIRMATION] SP Secret Renewed: {app_name}", 
            renewal_email(user_name, app_name, client_id, expires_on)
        )
        # Mark as notified for 'renewal' to ensure confirmation is only sent once.
        user_service.mark_as_notified(secret_id, "notified_renewal")

    print("✅ Secret monitoring check completed.")

if __name__ == "__main__":
    main()
