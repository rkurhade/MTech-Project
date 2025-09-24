import pytz
from flask_mail import Message
from datetime import datetime, timedelta, timezone

class AppController:
    def __init__(self, azure_ad_client, mail):
        self.azure_ad_client = azure_ad_client
        self.mail = mail
        self.ist = pytz.timezone("Asia/Kolkata")
        # Store created apps in-memory (for demonstration)
        self.created_apps = []

    # ----------------- Helper -----------------
    def _build_email_html(self, user_name, app_name, client_id, client_secret, expires_on):
        expires_str = expires_on.astimezone(self.ist).strftime('%Y-%m-%d %H:%M:%S')
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <p>Hi {user_name},</p>
                <p>Your Azure Service Principal has been created successfully.</p>
                <p>Service Principal Name: {app_name}<br>
                Client ID: {client_id}<br>
                Client Secret: {client_secret}<br>
                Tenant ID: {self.azure_ad_client.tenant_id}<br>
                Secret Expiry (IST): {expires_str}</p>
                <p><strong>Please store these credentials securely.</strong></p>
                <p>Best Regards,<br>Azure Service Principal Automation Team</p>
            </body>
        </html>
        """
        return html

    def _send_email(self, recipient, subject, html):
        msg = Message(subject=subject, recipients=[recipient], html=html)
        self.mail.send(msg)

    # ----------------- Core Methods -----------------
    def create_application(self, user_name, email, app_name):
        token = self.azure_ad_client.get_access_token()
        if not token:
            return {'error': 'Failed to obtain access token from Azure Entra ID.'}, 500

        existing_app = self.azure_ad_client.search_application(token, app_name)
        if existing_app:
            return {
                'error': f"Service Principal '{app_name}' already exists.",
                'app_id': existing_app['id'],
                'client_id': existing_app['appId']
            }, 409

        client_id, client_secret = self.azure_ad_client.create_application(token, app_name)
        if not client_id or not client_secret:
            return {'error': 'Failed to create Service Principal.'}, 500

        expires_on = datetime.now(timezone.utc) + timedelta(days=730)  # 24 months expiry
        self.created_apps.append((user_name, email, app_name, expires_on))

        email_html = self._build_email_html(user_name, app_name, client_id, client_secret, expires_on)
        self._send_email(email, f"Azure Service Principal Credentials for '{app_name}'", email_html)

        return {
            'message': f"Azure Service Principal '{app_name}' created successfully. Credentials emailed to {email}.",
            'client_id': client_id,
            'tenant_id': self.azure_ad_client.tenant_id
        }, 200

    def send_upcoming_expiry_notifications(self, days=30):
        now = datetime.now(timezone.utc)
        notifications_sent = 0

        for user_name, email, app_name, expires_on in self.created_apps:
            if 0 < (expires_on - now).days <= days:
                html = f"<p>Hi {user_name}, your SP '{app_name}' expires on {expires_on} UTC.</p>"
                self._send_email(email, f"[Upcoming Expiry] SP '{app_name}'", html)
                notifications_sent += 1

        return {'message': f'{notifications_sent} upcoming expiry notifications sent.'}, 200

    def send_expired_notifications(self):
        now = datetime.now(timezone.utc)
        notifications_sent = 0

        for user_name, email, app_name, expires_on in self.created_apps:
            if expires_on < now:
                html = f"<p>Hi {user_name}, your SP '{app_name}' expired on {expires_on} UTC.</p>"
                self._send_email(email, f"[Expired] SP '{app_name}'", html)
                notifications_sent += 1

        return {'message': f'{notifications_sent} expired notifications sent.'}, 200
