import os
import pyodbc
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

def handle_expired_secrets():
    try:
        sql_server = os.getenv('DB_SERVER')
        print(f"DB_SERVER env var: {sql_server}")
        if sql_server is None:
            return {"status": "error", "message": "DB_SERVER env var is None"}

        database = os.getenv('DB_DATABASE')
        username = os.getenv('DB_USERNAME')
        password = os.getenv('DB_PASSWORD')
        driver = '{ODBC Driver 17 for SQL Server}'

        smtp_server = os.getenv('MAIL_SERVER')
        from_email = os.getenv('MAIL_DEFAULT_SENDER')

        conn_str = f"""
            DRIVER={driver};
            SERVER={sql_server};
            DATABASE={database};
            UID={username};
            PWD={password};
            Encrypt=yes;
            TrustServerCertificate=no;
            Connection Timeout=30;
        """

        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        query = """
        SELECT id, user_name, email, app_name, expires_on
        FROM dbo.user_info
        WHERE 
            expires_on BETWEEN GETUTCDATE() AND DATEADD(DAY, 30, GETUTCDATE())
            AND (notified = 0 OR notified IS NULL)
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        notified_users = []

        for row in rows:
            user_id, user_name, email, app_name, expires_on = row

            subject = f"[Secret Expiry Alert] App '{app_name}' expires on {expires_on.date()}"
            body = f"""
Hi {user_name},

The client secret for your app '{app_name}' is expiring on {expires_on.date()}.

Please renew it before it expires to avoid service disruption.

Regards,
Azure Automation Team
"""

            msg = MIMEText(body, "plain")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = email

            try:
                with smtplib.SMTP(smtp_server) as server:
                    server.send_message(msg)

                cursor.execute("UPDATE dbo.user_info SET notified = 1 WHERE id = ?", user_id)
                conn.commit()
                notified_users.append(email)

            except Exception as e:
                print(f"Failed to send email to {email} - {e}")

        cursor.close()
        conn.close()

        return {"status": "success", "notified": notified_users}

    except Exception as e:
        return {"status": "error", "message": str(e)}