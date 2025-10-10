import pyodbc
from datetime import datetime, timedelta, timezone
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# === Load .env file for local testing ===
load_dotenv()

# === Database Configuration ===
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
                f'SERVER={self.server};DATABASE={self.database};'
                f'UID={self.username};PWD={self.password}'
            )
            return conn
        except Exception as e:
            print(f"[ERROR] Database connection error: {e}")
            return None

# === User Service ===
class UserService:
    def __init__(self, db_config):
        self.db_config = db_config

    # Fetch secrets expiring in next 30 days and check last notification for repeat
    def get_expiring_soon(self, days=30, repeat_interval=2):
        conn = self.db_config.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc)
            future = now + timedelta(days=days)
            cursor.execute('''
                SELECT id, user_name, email, app_name, client_id, expires_on, notified_upcoming, last_notified_at
                FROM user_info
                WHERE expires_on BETWEEN ? AND ?
                AND (notified_upcoming = 0 OR last_notified_at IS NULL OR last_notified_at <= DATEADD(day, -?, GETDATE()))
            ''', (now, future, repeat_interval))
            return cursor.fetchall()
        except Exception as e:
            print(f"[ERROR] Failed to fetch upcoming expiring secrets: {e}")
            return []
        finally:
            conn.close()

    # Fetch secrets already expired and not yet notified or due for repeat
    def get_expired_secrets(self, repeat_interval=2):
        conn = self.db_config.connect()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc)
            cursor.execute('''
                SELECT id, user_name, email, app_name, client_id, expires_on, notified_expired, last_notified_at
                FROM user_info
                WHERE expires_on < ?
                AND (notified_expired = 0 OR last_notified_at IS NULL OR last_notified_at <= DATEADD(day, -?, GETDATE()))
            ''', (now, repeat_interval))
            return cursor.fetchall()
        except Exception as e:
            print(f"[ERROR] Failed to fetch expired secrets: {e}")
            return []
        finally:
            conn.close()

    # Mark a secret as notified
    def mark_as_notified(self, secret_id, column):
        conn = self.db_config.connect()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            if column not in ["notified_upcoming", "notified_expired", "notified_renewal"]:
                print(f"[ERROR] Invalid column name: {column}")
                return
            cursor.execute(f'''
                UPDATE user_info
                SET {column} = 1, last_notified_at = GETDATE()
                WHERE id = ?
            ''', (secret_id,))
            conn.commit()
        except Exception as e:
            print(f"[ERROR] Failed to update {column} flag for ID {secret_id}: {e}")
        finally:
            conn.close()

# === Email Setup ===
smtp_server = os.getenv("MAIL_SERVER", "smtp.gmail.com")
smtp_port = int(os.getenv("MAIL_PORT", 587))
smtp_user = os.getenv("MAIL_USERNAME")
smtp_pass = os.getenv("MAIL_PASSWORD")
sender_email = os.getenv("MAIL_DEFAULT_SENDER", smtp_user)

def send_email(to_email, subject, body_html):
    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(smtp_server, smtp_port) as server_conn:
            server_conn.starttls()
            server_conn.login(smtp_user, smtp_pass)
            server_conn.send_message(msg)

        print(f"📧 Email sent to {to_email} — {subject}")
    except Exception as e:
        print(f"⚠️ Failed to send email to {to_email}: {e}")

# === Email Templates ===
def expiring_email(user_name, app_name, client_id, expiry):
    return f"""
    <html><body>
    <p>Hi {user_name},</p>
    <p>⚠️ Your secret <b>{client_id}</b> for <b>{app_name}</b> is expiring soon on <b>{expiry.strftime('%Y-%m-%d')}</b>.</p>
    <p>Please renew it before it expires.</p>
    </body></html>
    """

def expired_email(user_name, app_name, client_id, expiry):
    return f"""
    <html><body>
    <p>Hi {user_name},</p>
    <p>🚨 The secret <b>{client_id}</b> for <b>{app_name}</b> expired on <b>{expiry.strftime('%Y-%m-%d')}</b>.</p>
    <p>Please generate a new secret immediately.</p>
    </body></html>
    """

def renewal_email(user_name, app_name, client_id, expiry):
    return f"""
    <html><body>
    <p>Hi {user_name},</p>
    <p>✅ The secret <b>{client_id}</b> for <b>{app_name}</b> has been renewed. New expiry: <b>{expiry.strftime('%Y-%m-%d')}</b>.</p>
    <p>Thank you for updating your secret!</p>
    </body></html>
    """

# === Main Function ===
def main():
    db_config = DatabaseConfig({
        "server": os.getenv("DB_SERVER"),
        "database": os.getenv("DB_DATABASE"),
        "username": os.getenv("DB_USERNAME"),
        "password": os.getenv("DB_PASSWORD")
    })
    db_config.validate()
    user_service = UserService(db_config)

    # --- Expiring soon (30 days notice, repeat every 2 days) ---
    for s in user_service.get_expiring_soon(days=30, repeat_interval=2):
        secret_id, user_name, email, app_name, client_id, expires_on, notified_upcoming, last_notified_at = s
        send_email(email, f"⚠️ Secret Expiring Soon: {app_name}", expiring_email(user_name, app_name, client_id, expires_on))
        user_service.mark_as_notified(secret_id, "notified_upcoming")

    # --- Already expired (repeat every 2 days until renewal) ---
    for s in user_service.get_expired_secrets(repeat_interval=2):
        secret_id, user_name, email, app_name, client_id, expires_on, notified_expired, last_notified_at = s
        send_email(email, f"🚨 Secret Expired: {app_name}", expired_email(user_name, app_name, client_id, expires_on))
        user_service.mark_as_notified(secret_id, "notified_expired")

    # --- Renewal confirmation ---
    # Fetch secrets that were expired but now renewed (expires_on in future)
    conn = db_config.connect()
    if conn:
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc)
            cursor.execute('''
                SELECT id, user_name, email, app_name, client_id, expires_on, notified_expired, notified_renewal
                FROM user_info
                WHERE expires_on >= ?
                AND notified_expired = 1
                AND (notified_renewal IS NULL OR notified_renewal = 0)
            ''', (now,))
            renewed_secrets = cursor.fetchall()
            for s in renewed_secrets:
                secret_id, user_name, email, app_name, client_id, expires_on, notified_expired, notified_renewal = s
                send_email(email, f"✅ Secret Renewed: {app_name}", renewal_email(user_name, app_name, client_id, expires_on))
                user_service.mark_as_notified(secret_id, "notified_renewal")
        finally:
            conn.close()

    print("✅ Secret monitoring check completed successfully.")

# === Entry Point ===
if __name__ == "__main__":
    main()