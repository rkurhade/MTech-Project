import pytz
from flask_mail import Message
from datetime import datetime, timezone

class AppController:
    def __init__(self, db_config, azure_ad_client, user_service, mail):
        self.db_config = db_config
        self.azure_ad_client = azure_ad_client
        self.user_service = user_service
        self.mail = mail
        self.ist = pytz.timezone("Asia/Kolkata")

    # ----------------- Helper -----------------
    def _build_email_html(self, user_name, app_name, expires_on, type="upcoming"):
        expires_str = expires_on.astimezone(self.ist).strftime('%Y-%m-%d %H:%M:%S')
        if type == "upcoming":
            message = f"""
            <p>Hi {user_name},</p>
            <p><strong>Heads up:</strong> Your Azure Service Principal secret for <strong>{app_name}</strong> will expire on <strong>{expires_str}</strong> (IST).</p>
            <p>Please renew it before expiry to avoid disruption.</p>
            """
            subject_prefix = "[Upcoming Expiry]"
        else:  # expired
            message = f"""
            <p>Hi {user_name},</p>
            <p><strong>Action Required:</strong> Your Azure Service Principal secret for <strong>{app_name}</strong> expired on <strong>{expires_str}</strong> (IST).</p>
            <p>Please generate a new secret to avoid service disruption.</p>
            """
            subject_prefix = "[Expired]"

        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                {message}
                <p>Best Regards,<br>Azure Service Principal Automation Team</p>
            </body>
        </html>
        """
        return html, subject_prefix

    def _send_email(self, recipient, subject, html):
        msg = Message(subject=subject, recipients=[recipient], html=html)
        self.mail.send(msg)

    # ----------------- Core Methods -----------------
    def create_application(self, user_name, email, app_name):
        self.db_config.validate()
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

        # Default expiry: 24 months
        expires_on = datetime.now(timezone.utc) + timedelta(days=730)
        success = self.user_service.store_user_data(user_name, email, app_name, expires_on)
        if not success:
            self.azure_ad_client.delete_application(token, client_id)
            return {'error': 'Failed to store user data in the database.'}, 500

        expires_on_ist_str = expires_on.astimezone(self.ist).strftime('%Y-%m-%d %H:%M:%S')
        email_html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <p>Hi {user_name},</p>
                <p>Your Azure Service Principal has been created successfully.</p>
                <p>Service Principal Name: {app_name}<br>
                Client ID: {client_id}<br>
                Client Secret: {client_secret}<br>
                Tenant ID: {self.azure_ad_client.tenant_id}<br>
                Secret Expiry (IST): {expires_on_ist_str}</p>
                <p><strong>Please store these credentials securely.</strong></p>
                <p>Best Regards,<br>Azure Service Principal Automation Team</p>
            </body>
        </html>
        """
        self._send_email(email, f"Azure Service Principal Credentials for '{app_name}'", email_html)

        return {
            'message': f"Azure Service Principal '{app_name}' created successfully. Credentials emailed to {email}.",
            'client_id': client_id,
            'tenant_id': self.azure_ad_client.tenant_id
        }, 200

    def send_upcoming_expiry_notifications(self, days=30):
        expiring_secrets = self.user_service.get_expiring_soon(days)
        for user_name, email, app_name, expires_on in expiring_secrets:
            html, subject_prefix = self._build_email_html(user_name, app_name, expires_on, type="upcoming")
            self._send_email(email, f"{subject_prefix} SP Secret for '{app_name}'", html)
            self.user_service.mark_as_notified(app_name, column="notified_upcoming")

        return {'message': f'Notifications sent for {len(expiring_secrets)} upcoming expiries.'}, 200

    def send_expired_notifications(self):
        expired_secrets = self.user_service.get_expired_secrets()
        for user_name, email, app_name, expires_on in expired_secrets:
            html, subject_prefix = self._build_email_html(user_name, app_name, expires_on, type="expired")
            self._send_email(email, f"{subject_prefix} SP Secret for '{app_name}'", html)
            self.user_service.mark_as_notified(app_name, column="notified_expired")

        return {'message': f'Expired notifications sent to {len(expired_secrets)} user(s).'}, 200
