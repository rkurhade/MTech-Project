import pytz
from flask_mail import Message
from datetime import datetime, timezone, timedelta

class AppController:
    def __init__(self, db_config, azure_ad_client, mail):
        self.db_config = db_config
        self.azure_ad_client = azure_ad_client
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
        else:
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
        conn = self.db_config.connect()
        if not conn:
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

        # Store in DB directly
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_info (user_name, email, app_name, expires_on, notified_upcoming, notified_expired) "
                "VALUES (%s, %s, %s, %s, 0, 0)",
                (user_name, email, app_name, expires_on)
            )
            conn.commit()
        except Exception as e:
            self.azure_ad_client.delete_application(token, client_id)
            return {'error': f'Failed to store user data in DB: {str(e)}'}, 500

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
        conn = self.db_config.connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_name, email, app_name, expires_on FROM user_info "
            "WHERE expires_on > UTC_TIMESTAMP() AND expires_on <= DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s DAY) "
            "AND notified_upcoming = 0", (days,)
        )
        expiring_secrets = cursor.fetchall()

        for user_name, email, app_name, expires_on in expiring_secrets:
            html, subject_prefix = self._build_email_html(user_name, app_name, expires_on, type="upcoming")
            self._send_email(email, f"{subject_prefix} SP Secret for '{app_name}'", html)
            cursor.execute(
                "UPDATE user_info SET notified_upcoming = 1 WHERE app_name = %s", (app_name,)
            )
        conn.commit()

        return {'message': f'Notifications sent for {len(expiring_secrets)} upcoming expiries.'}, 200

    def send_expired_notifications(self):
        conn = self.db_config.connect()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_name, email, app_name, expires_on FROM user_info "
            "WHERE expires_on <= UTC_TIMESTAMP() AND notified_expired = 0"
        )
        expired_secrets = cursor.fetchall()

        for user_name, email, app_name, expires_on in expired_secrets:
            html, subject_prefix = self._build_email_html(user_name, app_name, expires_on, type="expired")
            self._send_email(email, f"{subject_prefix} SP Secret for '{app_name}'", html)
            cursor.execute(
                "UPDATE user_info SET notified_expired = 1 WHERE app_name = %s", (app_name,)
            )
        conn.commit()

        return {'message': f'Expired notifications sent to {len(expired_secrets)} user(s).'}, 200
