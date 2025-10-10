import datetime
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from services import DatabaseConfig
from config import ConfigLoader


# ===============================
# CONFIGURATION
# ===============================
db_config = DatabaseConfig(ConfigLoader.load_db_config())
mail_config = ConfigLoader.load_mail_config()
azure_config = ConfigLoader.load_azure_ad_config()

SMTP_USER = mail_config["MAIL_USERNAME"]
SMTP_PASS = mail_config["MAIL_PASSWORD"]

TENANT_ID = azure_config["tenant_id"]
CLIENT_ID = azure_config["client_id"]
CLIENT_SECRET = azure_config["client_secret"]

EXPIRY_THRESHOLD_DAYS = 30
THROTTLE_DAYS = 2
# ===============================


def get_graph_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]


def get_latest_secret_expiry(app_name, token):
    url = f"https://graph.microsoft.com/v1.0/applications?$filter=displayName eq '{app_name}'&$select=passwordCredentials"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"⚠️ Failed Graph call for {app_name}: {response.text}")
        return None

    data = response.json()
    if not data.get("value"):
        return None

    secrets = data["value"][0].get("passwordCredentials", [])
    if not secrets:
        return None

    latest = max(datetime.datetime.fromisoformat(s["endDateTime"].replace("Z", "+00:00")) for s in secrets)
    return latest


def send_email(to_email, subject, html_body):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(mail_config["MAIL_SERVER"], mail_config["MAIL_PORT"]) as server:
        if mail_config["MAIL_USE_TLS"]:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    print(f"📧 Email sent → {to_email} | {subject}")


def main():
    conn = db_config.connect()
    if not conn:
        print("❌ Database connection failed.")
        return

    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_name, email, app_name, latest_expiry_date,
               notified_upcoming, notified_expired, notified_renewal_confirmed, last_notified_at
        FROM dbo.user_info
    """)
    rows = cursor.fetchall()

    token = get_graph_token()
    now = datetime.datetime.utcnow()

    for row in rows:
        (
            user_id,
            user_name,
            email,
            app_name,
            db_latest_expiry,
            notified_upcoming,
            notified_expired,
            notified_renewal_confirmed,
            last_notified_at
        ) = row

        latest_expiry = get_latest_secret_expiry(app_name, token)
        if not latest_expiry:
            continue

        # Update Graph sync timestamp
        cursor.execute("""
            UPDATE dbo.user_info SET last_successful_graph_sync_at = SYSUTCDATETIME()
            WHERE id = ?
        """, user_id)
        conn.commit()

        days_to_expiry = (latest_expiry - now).days
        recently_notified = (
            last_notified_at and (now - last_notified_at).days < THROTTLE_DAYS
        )

        # ✅ Renewal detected
        if db_latest_expiry and latest_expiry > db_latest_expiry and not notified_renewal_confirmed:
            send_email(
                email,
                f"✅ Secret renewed for {app_name}",
                f"<p>Hi {user_name},</p>"
                f"<p>Your secret for <b>{app_name}</b> has been renewed successfully.</p>"
                f"<p>New Expiry Date: {latest_expiry.strftime('%Y-%m-%d')}</p>"
            )
            cursor.execute("""
                UPDATE dbo.user_info
                SET latest_expiry_date=?, notified_renewal_confirmed=1,
                    notified_upcoming=0, notified_expired=0,
                    last_notified_at=SYSUTCDATETIME()
                WHERE id=?
            """, (latest_expiry, user_id))
            conn.commit()
            continue

        # 🔄 Keep DB expiry updated
        if not db_latest_expiry or latest_expiry != db_latest_expiry:
            cursor.execute("""
                UPDATE dbo.user_info SET latest_expiry_date=? WHERE id=?
            """, (latest_expiry, user_id))
            conn.commit()

        # ⚠️ Expiring soon
        if 0 < days_to_expiry <= EXPIRY_THRESHOLD_DAYS and not notified_upcoming and not recently_notified:
            send_email(
                email,
                f"⚠️ Secret expiring soon for {app_name}",
                f"<p>Hi {user_name},</p>"
                f"<p>The secret for <b>{app_name}</b> will expire on {latest_expiry.strftime('%Y-%m-%d')}.</p>"
                f"<p>Please renew it to avoid service interruption.</p>"
            )
            cursor.execute("""
                UPDATE dbo.user_info
                SET notified_upcoming=1, last_notified_at=SYSUTCDATETIME()
                WHERE id=?
            """, user_id)
            conn.commit()

        # 🚨 Already expired
        elif latest_expiry < now and not notified_expired and not recently_notified:
            send_email(
                email,
                f"🚨 Secret expired for {app_name}",
                f"<p>Hi {user_name},</p>"
                f"<p>The secret for <b>{app_name}</b> expired on {latest_expiry.strftime('%Y-%m-%d')}.</p>"
                f"<p>Please create a new secret immediately.</p>"
            )
            cursor.execute("""
                UPDATE dbo.user_info
                SET notified_expired=1, last_notified_at=SYSUTCDATETIME()
                WHERE id=?
            """, user_id)
            conn.commit()

    conn.close()
    print("✅ SPN expiry monitoring complete.")


if __name__ == "__main__":
    main()