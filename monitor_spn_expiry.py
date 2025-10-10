import pyodbc
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# =========================
# CONFIG
# =========================
DB_CONFIG = {
    'server': 'your_server',
    'database': 'your_db',
    'username': 'your_user',
    'password': 'your_pass'
}

GRAPH_CLIENT_ID = 'your_client_id'
GRAPH_CLIENT_SECRET = 'your_client_secret'
GRAPH_TENANT_ID = 'your_tenant_id'

SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USER = 'azurespnautomation@gmail.com'
SMTP_PASSWORD = 'your_smtp_password'

EXPIRY_NOTICE_DAYS = 30
REPEAT_NOTIFICATION_DAYS = 2

# =========================
# HELPER FUNCTIONS
# =========================

def get_sql_driver():
    """Return the best available SQL Server ODBC driver installed."""
    drivers = pyodbc.drivers()
    for drv in ['ODBC Driver 18 for SQL Server', 'ODBC Driver 17 for SQL Server', 'SQL Server Native Client 11.0']:
        if drv in drivers:
            return drv
    raise RuntimeError("No suitable SQL Server ODBC driver found. Install ODBC Driver 17 or 18.")

def get_db_connection():
    driver = get_sql_driver()
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['username']};"
        f"PWD={DB_CONFIG['password']};"
        "Encrypt=yes;TrustServerCertificate=yes"
    )
    return pyodbc.connect(conn_str)

def get_graph_token():
    url = f'https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token'
    data = {
        'client_id': GRAPH_CLIENT_ID,
        'scope': 'https://graph.microsoft.com/.default',
        'client_secret': GRAPH_CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    resp = requests.post(url, data=data)
    resp.raise_for_status()
    return resp.json()['access_token']

def get_app_secrets(access_token, app_name):
    url = f"https://graph.microsoft.com/v1.0/applications?$filter=displayName eq '{app_name}'&$select=id,displayName,passwordCredentials"
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    value = resp.json().get('value', [])
    if value:
        return value[0].get('passwordCredentials', [])
    return []

def send_email(to_email, subject, body):
    msg = MIMEText(body, 'html')
    msg['From'] = SMTP_USER
    msg['To'] = to_email
    msg['Subject'] = subject

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

# =========================
# MAIN SCRIPT
# =========================
def main():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_name, email, app_name, secret_id, latest_expiry_date, notified_upcoming, notified_expired, last_notified_at
        FROM dbo.user_info
    """)
    apps = cursor.fetchall()

    token = get_graph_token()
    now = datetime.utcnow()

    for app in apps:
        latest_expiry = datetime(1900,1,1)
        secrets = get_app_secrets(token, app.app_name)
        latest_secret_id = None

        # Find latest expiry secret
        for sec in secrets:
            end_dt = datetime.fromisoformat(sec['endDateTime'].replace('Z',''))
            if end_dt > latest_expiry:
                latest_expiry = end_dt
                latest_secret_id = sec.get('keyId')

        # Update latest expiry in DB
        if latest_expiry != app.latest_expiry_date:
            cursor.execute("""
                UPDATE dbo.user_info
                SET latest_expiry_date=?, secret_id=?, notified_upcoming=0, notified_expired=0
                WHERE id=?
            """, latest_expiry, latest_secret_id, app.id)
            conn.commit()
            # Send confirmation email
            send_email(
                app.email,
                f"SPN Secret Updated for {app.app_name}",
                f"Dear {app.user_name},<br><br>Your SPN secret for {app.app_name} has been updated. New expiry: {latest_expiry.date()}<br><br>Regards,<br>Azure Automation"
            )

        # Expired secrets
        if latest_expiry < now and (app.last_notified_at is None or app.last_notified_at < now - timedelta(days=REPEAT_NOTIFICATION_DAYS)):
            send_email(
                app.email,
                f"IMMEDIATE ACTION REQUIRED: SPN Secret Expired for {app.app_name}",
                f"Dear {app.user_name},<br><br>The SPN secret for {app.app_name} has expired!<br>Expiry: {latest_expiry.date()}<br><br>Renew immediately."
            )
            cursor.execute("""
                UPDATE dbo.user_info
                SET notified_expired=1, last_notified_at=SYSUTCDATETIME()
                WHERE id=?
            """, app.id)
            conn.commit()

        # Expiring soon secrets
        elif now <= latest_expiry <= now + timedelta(days=EXPIRY_NOTICE_DAYS) and (app.last_notified_at is None or app.last_notified_at < now - timedelta(days=REPEAT_NOTIFICATION_DAYS)):
            send_email(
                app.email,
                f"Action Required: SPN Secret Expiring Soon for {app.app_name}",
                f"Dear {app.user_name},<br><br>The SPN secret for {app.app_name} is expiring soon.<br>Expiry: {latest_expiry.date()}<br>Please renew before the expiry date."
            )
            cursor.execute("""
                UPDATE dbo.user_info
                SET notified_upcoming=1, last_notified_at=SYSUTCDATETIME()
                WHERE id=?
            """, app.id)
            conn.commit()

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
