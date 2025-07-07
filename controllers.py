from flask_mail import Message
from datetime import datetime, timedelta
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
        if is_testing:
            print("[INFO] EXPIRY_TEST_MODE is ON: Using 1-minute expiry.")
            expires_on = datetime.utcnow() + timedelta(minutes=1)
        else:
            print("[INFO] EXPIRY_TEST_MODE is OFF: Using 24-month expiry.")
            expires_on = datetime.utcnow() + timedelta(days=730)

        success = self.user_service.store_user_data(user_name, email, app_name, expires_on)
        if not success:
            print("[ERROR] Failed to store user data.")
            self.azure_ad_client.delete_application(token, client_id)
            return {'error': 'Failed to store user data in the database.'}, 500

        tenant_id = self.azure_ad_client.tenant_id
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
            'message': f"Azure Service Principal created successfully for '{app_name}'. Credentials have been emailed to {email}.",
            'client_id': client_id,
            'tenant_id': tenant_id,
        }, 200

    def send_expiry_notifications(self, days_before_expiry=1):
        expiring_secrets = self.user_service.get_expiring_secrets(days_before_expiry)
        if not expiring_secrets:
            print("[INFO] No expiring secrets found.")
            return {'message': 'No expiring secrets found.'}, 200

        for user_name, email, app_name, expires_on in expiring_secrets:
            try:
                days_left = (expires_on - datetime.utcnow()).days
                email_body_html = f"""
                <html>
                <body style="font-family: Arial, sans-serif; color: #333;">
                    <p>Hi {user_name},</p>
                    <p>Your Azure Service Principal secret for application <strong>{app_name}</strong> will expire in <strong>{days_left} day(s)</strong> (on {expires_on.strftime('%Y-%m-%d %H:%M:%S UTC')}).</p>
                    <p>Please rotate your secret or create a new one to avoid service disruption.</p>
                    <p>Best Regards,<br>Azure Service Principal Automation Team</p>
                </body>
                </html>
                """

                msg = Message(
                    subject=f"Azure Service Principal Secret Expiry Warning for '{app_name}'",
                    recipients=[email],
                    html=email_body_html
                )
                self.mail.send(msg)
                print(f"[INFO] Expiry notification sent to {email} for app {app_name}")
            except Exception as e:
                print(f"[ERROR] Failed to send expiry email to {email}: {e}")

        return {'message': f'Expiry notifications sent to {len(expiring_secrets)} user(s).'}, 200