import pytz
from flask_mail import Message
from datetime import datetime, timedelta, timezone
import os

class AppController:
    def __init__(self, db_config, azure_ad_client, user_service, mail):
        self.db_config = db_config
        self.azure_ad_client = azure_ad_client
        self.user_service = user_service
        self.mail = mail

    def create_application(self, user_name, email, app_name):
        try:
            self.db_config.validate()
        except ValueError as e:
            return {'error': str(e)}, 400

        print("[DEBUG] Starting app creation for:", app_name)

        if self.db_config.connect() is None:
            print("[ERROR] Could not establish DB connection")
            return {'error': 'Failed to connect to database.'}, 500

        token = self.azure_ad_client.get_access_token()
        if not token:
            print("[ERROR] Token fetch failed.")
            return {'error': 'Failed to obtain access token from Azure Entra ID.'}, 500

        existing_app = self.azure_ad_client.search_application(token, app_name)
        if existing_app:
            print("[ERROR] App already exists:", app_name)
            return {
                'error': f"Service Principal with name '{app_name}' already exists.",
                'app_id': existing_app['id'],
                'client_id': existing_app['appId']
            }, 409

        client_id, client_secret = self.azure_ad_client.create_application(token, app_name)
        if not client_id or not client_secret:
            print("[ERROR] Failed to create SP.")
            return {'error': 'Failed to create Service Principal in Azure Entra ID.'}, 500

        is_testing = os.environ.get("EXPIRY_TEST_MODE", "False").lower() == "true"
        now_utc = datetime.now(timezone.utc)

        if is_testing:
            print("[INFO] EXPIRY_TEST_MODE is ON: Using 1-minute expiry.")
            expires_on = now_utc + timedelta(minutes=1)
        else:
            print("[INFO] EXPIRY_TEST_MODE is OFF: Using 24-month expiry.")
            expires_on = now_utc + timedelta(days=730)

        success = self.user_service.store_user_data(user_name, email, app_name, expires_on)
        if not success:
            print("[ERROR] Failed to store user data.")
            self.azure_ad_client.delete_application(token, client_id)
            return {'error': 'Failed to store user data in the database.'}, 500

        tenant_id = self.azure_ad_client.tenant_id
        ist = pytz.timezone("Asia/Kolkata")
        expires_on_ist_str = expires_on.astimezone(ist).strftime('%Y-%m-%d %H:%M:%S')

        email_body_html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333;">
            <p>Hi {user_name},</p>
            <p>Your Azure Service Principal has been created successfully. Please find the credentials below:</p>
            <table style="border-collapse: collapse; margin-top: 10px;">
              <tr><td style="padding: 8px; font-weight: bold;">Service Principal Name:</td><td style="padding: 8px;">{app_name}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">Client ID:</td><td style="padding: 8px;">{client_id}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">Client Secret:</td><td style="padding: 8px;">{client_secret}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">Tenant ID:</td><td style="padding: 8px;">{tenant_id}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">Secret Expiry (IST):</td><td style="padding: 8px;">{expires_on_ist_str}</td></tr>
            </table>
            <p><strong>NOTE: Secret is valid for {'1 minute' if is_testing else '24 months'} from date of creation</strong>.</p>
            <p><strong>Please store these credentials securely</strong>. Do not share them with unauthorized users.</p>
            <p>Best Regards,<br>Azure Service Principal Automation Team</p>
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
            'message': f"Azure Service Principal has been created successfully with name '{app_name}'. Credentials have been emailed to {email}.",
            'client_id': client_id,
            'tenant_id': tenant_id,
        }, 200

    def send_upcoming_expiry_notifications(self, days=3):
        ist = pytz.timezone("Asia/Kolkata")
        expiring_secrets = self.user_service.get_expiring_soon(days)

        if not expiring_secrets:
            print(f"[INFO] No secrets expiring in next {days} day(s).")
            return {'message': f'No secrets expiring in next {days} day(s).'}, 200

        for user_name, email, app_name, expires_on in expiring_secrets:
            try:
                expires_on_ist = expires_on.astimezone(ist)
                print(f"[DEBUG] Expiring soon: {app_name} - {expires_on_ist}")

                email_body_html = f"""
                <html>
                  <body style="font-family: Arial, sans-serif; color: #333;">
                    <p>Hi {user_name},</p>
                    <p><strong>Heads up:</strong> Your Azure Service Principal secret for <strong>{app_name}</strong> will expire on <strong>{expires_on_ist.strftime('%Y-%m-%d %H:%M:%S')}</strong> (IST).</p>
                    <p>Please renew it before expiry to avoid disruption.</p>
                    <p>Best Regards,<br>Azure Service Principal Automation Team</p>
                  </body>
                </html>
                """

                msg = Message(
                    subject=f"[Upcoming Expiry] SP Secret for '{app_name}'",
                    recipients=[email],
                    html=email_body_html
                )
                self.mail.send(msg)

                self.user_service.mark_as_notified(app_name, column="notified_upcoming")

            except Exception as e:
                print(f"[ERROR] Failed to send upcoming expiry email to {email}: {e}")

        return {'message': f'Notifications sent for {len(expiring_secrets)} upcoming expiries.'}, 200

    def send_expired_notifications(self):
        ist = pytz.timezone("Asia/Kolkata")
        expired_secrets = self.user_service.get_expired_secrets()

        if not expired_secrets:
            print("[INFO] No expired secrets found.")
            return {'message': 'No expired secrets found.'}, 200

        for user_name, email, app_name, expires_on in expired_secrets:
            try:
                expires_on_ist = expires_on.astimezone(ist)
                print(f"[DEBUG] Expired app: {app_name}, Email: {email}")

                email_body_html = f"""
                <html>
                    <body style="font-family: Arial, sans-serif; color: #333;">
                        <p>Hi {user_name},</p>
                        <p><strong>Action Required:</strong> Your Azure Service Principal secret for <strong>{app_name}</strong> expired on <strong>{expires_on_ist.strftime('%Y-%m-%d %H:%M:%S')}</strong> (IST).</p>
                        <p>Please generate a new secret to avoid service disruption.</p>
                        <p>Best Regards,<br>Azure Service Principal Automation Team</p>
                    </body>
                </html>
                """

                msg = Message(
                    subject=f"[Expired] SP Secret for '{app_name}'",
                    recipients=[email],
                    html=email_body_html
                )
                self.mail.send(msg)

                self.user_service.mark_as_notified(app_name, column="notified_expired")

            except Exception as e:
                print(f"[ERROR] Failed to send expired email to {email}: {e}")

        return {'message': f'Expired notifications sent to {len(expired_secrets)} user(s).'}, 200