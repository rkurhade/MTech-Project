import pyodbc
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText

# DB connection from GitHub Secrets
conn_str = (
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={os.getenv('DB_SERVER')};"
    f"DATABASE={os.getenv('DB_NAME')};"
    f"UID={os.getenv('DB_USER')};"
    f"PWD={os.getenv('DB_PASSWORD')}"
)

# Connect to DB
try:
    conn = pyodbc.connect(conn_str)
    print("[INFO] Connected to DB.")
except Exception as e:
    print(f"[ERROR] DB connection failed: {e}")
    exit(1)

cursor = conn.cursor()

# 🔍 Find Service Principals expiring in next 2 minutes
target_time = datetime.utcnow() + timedelta(minutes=2)
cursor.execute("SELECT user_name, email, app_name, expires_on FROM user_info WHERE expires_on <= ?", target_time)
results = cursor.fetchall()

if not results:
    print("[INFO] No upcoming expiries in the next 2 minutes.")
    exit(0)

# SMTP email config from GitHub Secrets
smtp_server = os.getenv("MAIL_SERVER")
smtp_port = int(os.getenv("MAIL_PORT"))
smtp_user = os.getenv("MAIL_USERNAME")
smtp_pass = os.getenv("MAIL_PASSWORD")
sender = os.getenv("MAIL_SENDER")

# 📧 Send email to each user
for user_name, email, app_name, expires_on in results:
    subject = f"⏰ URGENT: Secret expiring soon for '{app_name}'"
    body = f"""
Hi {user_name},

⚠️ This is an automated reminder that the Azure Service Principal **{app_name}** is about to expire at:

👉 **{expires_on} UTC**

Please take necessary action if this SP is still in use.

Regards,  
Azure SP Automation Bot
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender, [email], msg.as_string())
        print(f"[INFO] Sent expiry reminder to {email} for '{app_name}'")
    except Exception as e:
        print(f"[ERROR] Failed to send email to {email}: {e}")

cursor.close()
conn.close()