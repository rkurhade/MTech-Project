import datetime
import smtplib
import pyodbc
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# === Read from Azure App Service Environment Variables ===
server = os.getenv("DB_SERVER")
database = os.getenv("DB_DATABASE")
username = os.getenv("DB_USERNAME")
password = os.getenv("DB_PASSWORD")

smtp_server = os.getenv("MAIL_SERVER", "smtp.gmail.com")
smtp_port = int(os.getenv("MAIL_PORT", 587))
smtp_user = os.getenv("MAIL_USERNAME")
smtp_pass = os.getenv("MAIL_PASSWORD")
sender_email = os.getenv("MAIL_DEFAULT_SENDER", smtp_user)

# === Validate DB Configuration ===
missing = [k for k, v in {
    "DB_SERVER": server,
    "DB_DATABASE": database,
    "DB_USERNAME": username,
    "DB_PASSWORD": password,
}.items() if not v]
if missing:
    raise EnvironmentError(f"❌ Missing DB config environment variables: {missing}")

# === Connect to SQL Database ===
def get_connection():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};DATABASE={database};UID={username};PWD={password};Encrypt=yes;TrustServerCertificate=no;"
    )

# === Email Sending Function ===
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

        print(f"📧 Email sent successfully to {to_email} — {subject}")
    except Exception as e:
        print(f"⚠️ Failed to send email to {to_email}: {e}")

# === Email Templates ===
def expiring_email(user_name, app_name, expiry):
    return f"""
    <html><body>
    <p>Hi {user_name},</p>
    <p>⚠️ Your secret for <b>{app_name}</b> is expiring soon on <b>{expiry.strftime('%Y-%m-%d')}</b>.</p>
    <p>Please renew it before it expires to avoid service disruption.</p>
    <p>Best,<br>Azure Automation Team</p>
    </body></html>
    """

def expired_email(user_name, app_name, expiry):
    return f"""
    <html><body>
    <p>Hi {user_name},</p>
    <p>🚨 The secret for <b>{app_name}</b> expired on <b>{expiry.strftime('%Y-%m-%d')}</b>.</p>
    <p>Please generate a new secret immediately and update dependent systems.</p>
    <p>Best,<br>Azure Automation Team</p>
    </body></html>
    """

def renewal_email(user_name, app_name, expiry):
    return f"""
    <html><body>
    <p>Hi {user_name},</p>
    <p>✅ The secret for <b>{app_name}</b> has been renewed successfully. New expiry: <b>{expiry.strftime('%Y-%m-%d')}</b>.</p>
    <p>Thank you for keeping your credentials updated!</p>
    <p>Best,<br>Azure Automation Team</p>
    </body></html>
    """

# === Main Logic ===
def main():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, user_name, email, app_name, latest_expiry_date, 
               notified_upcoming, notified_expired, notified_renewal_confirmed
        FROM dbo.user_info
    """)
    rows = cursor.fetchall()

    now = datetime.datetime.utcnow()

    for row in rows:
        (user_id, user_name, email, app_name, expiry,
         notified_upcoming, notified_expired, renewal_confirmed) = row

        if not expiry:
            continue

        days_to_expiry = (expiry - now).days

        # === Case 1: Expiring soon ===
        if 0 < days_to_expiry <= 7 and not notified_upcoming:
            send_email(
                email,
                f"⚠️ SPN Secret Expiring Soon for {app_name}",
                expiring_email(user_name, app_name, expiry)
            )
            cursor.execute("""
                UPDATE dbo.user_info 
                SET notified_upcoming=1, last_notified_at=SYSUTCDATETIME() 
                WHERE id=?
            """, user_id)

        # === Case 2: Already expired ===
        elif expiry < now and not notified_expired:
            send_email(
                email,
                f"🚨 SPN Secret Expired for {app_name}",
                expired_email(user_name, app_name, expiry)
            )
            cursor.execute("""
                UPDATE dbo.user_info 
                SET notified_expired=1, last_notified_at=SYSUTCDATETIME() 
                WHERE id=?
            """, user_id)

        # === Case 3: Renewal confirmation ===
        elif expiry > now and notified_expired and not renewal_confirmed:
            send_email(
                email,
                f"✅ SPN Secret Renewed for {app_name}",
                renewal_email(user_name, app_name, expiry)
            )
            cursor.execute("""
                UPDATE dbo.user_info 
                SET notified_renewal_confirmed=1, 
                    notified_expired=0, 
                    notified_upcoming=0, 
                    last_notified_at=SYSUTCDATETIME()
                WHERE id=?
            """, user_id)

    conn.commit()
    conn.close()
    print("✅ Secret monitoring check completed successfully.")

# === Entry point for Azure WebJob or Scheduler ===
if __name__ == "__main__":
    main()
