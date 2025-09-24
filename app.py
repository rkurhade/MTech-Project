import pytz
from flask_mail import Message
from datetime import datetime, timedelta, timezone

class AppController:
    def __init__(self, db_config, azure_ad_client, mail):
        self.db_config = db_config
        self.azure_ad_client = azure_ad_client
        self.mail = mail

    # ------------------- Helper DB Methods -------------------
    def store_user_data(self, user_name, email, app_name, expires_on):
        try:
            query = """
            INSERT INTO dbo.user_info (user_name, email, app_name, expires_on, notified_upcoming, notified_expired)
            VALUES (%s, %s, %s, %s, 0, 0)
            """
            conn = self.db_config.connect()
            cursor = conn.cursor()
            cursor.execute(query, (user_name, email, app_name, expires_on))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to store user data: {e}")
            return False

    def get_expiring_soon(self, days=30):
        try:
            query = """
            SELECT user_name, email, app_name, expires_on
            FROM dbo.user_info
            WHERE expires_on > SYSUTCDATETIME()
              AND expires_on <= DATEADD(day, %s, SYSUTCDATETIME())
              AND notified_upcoming = 0
            """
            conn = self.db_config.connect()
            cursor = conn.cursor()
            cursor.execute(query, (days,))
            results = cursor.fetchall()
            cursor.close()
            conn.close()
            return results
        except Exception as e:
            print(f"[ERROR] Failed to fetch expiring soon secrets: {e}")
            return []

    def get_expired_secrets(self):
        try:
            query = """
            SELECT user_name, email, app_name, expires_on
            FROM dbo.user_info
            WHERE expires_on <= SYSUTCDATETIME()
              AND notified_expired = 0
            """
            conn = self.db_config.connect()
            cursor = conn.cursor()
            cursor.execute(query)
            results = cursor.fetchall()
            cursor.close()
            conn.close()
            return results
        except Exception as e:
            print(f"[ERROR] Failed to fetch expired secrets: {e}")
            return []

    def mark_as_notified(self, app_name, column="notified_upcoming"):
        try:
            query = f"UPDATE dbo.user_info SET {column} = 1 WHERE app_name = %s"
            conn = self.db_config.connect()
            cursor = conn.cursor()
            cursor.execute(query, (app_name,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[ERROR] Failed to mark {column} for {app_name}: {e}")

    # ------------------- Application Creation -------------------
    def create_application(self, user_name, email, app_name):
        try:
            self.db_config.validate()
        except ValueError as e:
            return {'error': str(e)}, 400

        print("[DEBUG] Starting app creation for:", app_name)

        if self.db_config.connect() is None:
            return {'error': 'Failed to connect to database.'}, 500

        token = self.azure_ad_client.get_access_token()
        if not token:
            return {'error': 'Failed to obtain access token from Azure Entra ID.'}, 500

        existing_app = self.azure_ad_client.search_application(token, app_name)
        if existing_app:
            return {
                'error': f"Service Principal with name '{app_name}' already exists.",
                'app_id': existing_app['id'],
                'client_id': existing_app['appId']
            }, 409

        client_id, client_secret = self.azure_ad_client.create_application(token, app_name)
        if not client_id or not client_secret:
            return {'error': 'Failed to create Service Principal in Azure Entra ID.'}, 500

        now_utc = datetime.now(timezone.utc)
        expires_on = now_utc + timedelta(days=730)  # 24-month expiry

        success = self.store_user_data(user_name, email, app_name, expires_on)
        if not success:
            self.azure_ad_client.delete_application(token, client_id)
            return {'error': 'Failed to store user data in the database.'}, 500

        tenant_id = self.azure_ad_client.tenant_id
        ist = pytz.timezone("Asia/Kolkata")
        expires_on_ist_str = expires_on.astimezone(ist).strftime('%Y-%m-%d %H:%M:%S')

        email_body_html = f"""
        <html>
          <body>
            <p>Hi {user_name},</p>
            <p>Your Azure Service Principal has been created successfully:</p>
            <ul>
                <li>App Name: {app_name}</li>
                <li>Client ID: {client_id}</li>
                <li>Client Secret: {client_secret}</li>
                <li>Tenant ID: {tenant_id}</li>
                <li>Secret Expiry (IST): {expires_on_ist_str}</li>
            </ul>
            <p>Please store credentials securely.</p>
          </body>
        </html>
        """

        try:
            msg = Message(
                subject=f"Azure Service Principal Credentials for '{app_name}'",
                recipients=[email],
                html=email_body_html
            )
            self.mail.send(msg)
        except Exception as e:
            print(f"[ERROR] Failed to send email: {e}")
            return {'error': f'Failed to send email: {str(e)}'}, 500

        return {
            'message': f"Azure Service Principal '{app_name}' created and emailed to {email}.",
            'client_id': client_id,
            'tenant_id': tenant_id
        }, 200

    # ------------------- Expiry Notifications -------------------
    def send_upcoming_expiry_notifications(self, days=30):
        ist = pytz.timezone("Asia/Kolkata")
        expiring_secrets = self.get_expiring_soon(days)

        if not expiring_secrets:
            return {'message': f'No secrets expiring in next {days} day(s).'}, 200

        for user_name, email, app_name, expires_on in expiring_secrets:
            try:
                expires_on_ist = expires_on.astimezone(ist)
                email_body_html = f"""
                <html>
                  <body>
                    <p>Hi {user_name},</p>
                    <p>Your SP secret for {app_name} will expire on {expires_on_ist.strftime('%Y-%m-%d %H:%M:%S')} (IST).</p>
                    <p>Please renew it before expiry.</p>
                  </body>
                </html>
                """
                msg = Message(
                    subject=f"[Upcoming Expiry] SP Secret for '{app_name}'",
                    recipients=[email],
                    html=email_body_html
                )
                self.mail.send(msg)
                self.mark_as_notified(app_name, column="notified_upcoming")
            except Exception as e:
                print(f"[ERROR] Failed to send upcoming expiry email to {email}: {e}")

        return {'message': f'Notifications sent for {len(expiring_secrets)} upcoming expiries.'}, 200

    def send_expired_notifications(self):
        ist = pytz.timezone("Asia/Kolkata")
        expired_secrets = self.get_expired_secrets()

        if not expired_secrets:
            return {'message': 'No expired secrets found.'}, 200

        for user_name, email, app_name, expires_on in expired_secrets:
            try:
                expires_on_ist = expires_on.astimezone(ist)
                email_body_html = f"""
                <html>
                  <body>
                    <p>Hi {user_name},</p>
                    <p>Your SP secret for {app_name} expired on {expires_on_ist.strftime('%Y-%m-%d %H:%M:%S')} (IST).</p>
                    <p>Please generate a new secret to avoid service disruption.</p>
                  </body>
                </html>
                """
                msg = Message(
                    subject=f"[Expired] SP Secret for '{app_name}'",
                    recipients=[email],
                    html=email_body_html
                )
                self.mail.send(msg)
                self.mark_as_notified(app_name, column="notified_expired")
            except Exception as e:
                print(f"[ERROR] Failed to send expired email to {email}: {e}")

        return {'message': f'Expired notifications sent to {len(expired_secrets)} user(s).'}, 200
