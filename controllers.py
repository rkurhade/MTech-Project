# controllers.py
import pytz
from flask_mail import Message
from datetime import datetime, timedelta, timezone
import os
import requests

class AppController:
    def __init__(self, db_config, azure_ad_client, user_service, mail):
        self.db_config = db_config
        self.azure_ad_client = azure_ad_client
        self.user_service = user_service
        self.mail = mail
        self.ist = pytz.timezone("Asia/Kolkata")

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

        # Add owner to the application (registered user)
        try:
            app_obj = self.azure_ad_client.search_application(token, app_name)
            app_object_id = app_obj['id'] if app_obj else None
            if not app_object_id:
                raise Exception("Could not find created app object id.")

            owner_result = self.azure_ad_client.add_owner_to_application(token, app_object_id, email)
            if owner_result:
                print(f"[INFO] Added owner {email} to app {app_name}")
            else:
                print(f"[ERROR] Failed to add owner {email} to app {app_name}")
        except Exception as e:
            print(f"[ERROR] Could not add owner to app: {e}")

        # Determine expiry based on testing mode
        is_testing = os.environ.get("EXPIRY_TEST_MODE", "False").lower() == "true"
        now_utc = datetime.now(timezone.utc)

        if is_testing:
            print("[INFO] EXPIRY_TEST_MODE is ON: Using 10-minute expiry.")
            expires_on = now_utc + timedelta(minutes=10)
        else:
            print("[INFO] EXPIRY_TEST_MODE is OFF: Using 24-month expiry.")
            expires_on = now_utc + timedelta(days=730)


        # Prepare secret_info for app_secrets (no latest column)
        secret_info = {
            'key_id': 'initial',  # You may want to fetch the real key_id from Azure response
            'end_date': expires_on,
            'display_name': f"{app_name} secret"
        }
        success = self.user_service.store_user_and_secret(user_name, email, app_name, secret_info)
        if not success:
            print("[ERROR] Failed to store user and secret data.")
            self.azure_ad_client.delete_application(token, client_id)
            return {'error': 'Failed to store user/secret data in the database.'}, 500

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
            <p><strong>NOTE: Secret is valid for {'10 minute' if is_testing else '24 months'} from date of creation</strong>.</p>
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

    # NEW: Method to handle the secret renewal process
    def renew_application_secret(self, app_name):
        """
        Renews the secret for an existing application by creating a new one.
        """
        print(f"[DEBUG] Starting secret renewal for: {app_name}")

        token = self.azure_ad_client.get_access_token()
        if not token:
            print("[ERROR] Token fetch failed during renewal.")
            return {'error': 'Failed to obtain access token from Azure Entra ID.'}, 500

        app_obj = self.azure_ad_client.get_application_with_secrets(token, app_name)
        if not app_obj:
            print(f"[ERROR] Application not found for renewal: {app_name}")
            return {'error': f"Application '{app_name}' not found in Azure Entra ID."}, 404

        app_object_id = app_obj['id']

        client_id = app_obj.get('appId') # Use appId from the fetched object
        new_secret = self.azure_ad_client.add_password_to_application(token, app_object_id, app_name)
        if not new_secret:
            print(f"[ERROR] Failed to create new secret for app: {app_name}")
            return {'error': 'Failed to create new secret in Azure Entra ID.'}, 500

        is_testing = os.environ.get("EXPIRY_TEST_MODE", "False").lower() == "true"
        now_utc = datetime.now(timezone.utc)
        new_expiry_date = now_utc + timedelta(minutes=10) if is_testing else now_utc + timedelta(days=730)

        # Prepare secret_info for app_secrets (no latest column)
        secret_info = {
            'key_id': 'renewed',  # You may want to fetch the real key_id from Azure response
            'end_date': new_expiry_date,
            'display_name': f"{app_name} secret renewed"
        }
        success = self.user_service.add_new_secret(app_name, secret_info)
        if not success:
            print(f"[ERROR] Could not update local DB for app: {app_name}")
            return {'error': 'Secret created in Azure, but could not update local database. Please contact support.'}, 500

        # Get user details for email
        conn = self.db_config.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT user_name, email FROM user_info WHERE app_name = ? ORDER BY created_date DESC", (app_name,))
        row = cursor.fetchone()
        user_name = row[0] if row else None
        email = row[1] if row else None
        conn.close()

        tenant_id = self.azure_ad_client.tenant_id
        expires_on_ist_str = new_expiry_date.astimezone(self.ist).strftime('%Y-%m-%d %H:%M:%S')

        email_body_html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333;">
            <p>Hi {user_name},</p>
            <p>The client secret for your Azure Service Principal <strong>'{app_name}'</strong> has been successfully renewed.</p>
            <p>Please find the new credentials below:</p>
            <table style="border-collapse: collapse; margin-top: 10px;">
              <tr><td style="padding: 8px; font-weight: bold;">Service Principal Name:</td><td style="padding: 8px;">{app_name}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">Client ID:</td><td style="padding: 8px;">{client_id}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">New Client Secret:</td><td style="padding: 8px;">{new_secret}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">Tenant ID:</td><td style="padding: 8px;">{tenant_id}</td></tr>
              <tr><td style="padding: 8px; font-weight: bold;">New Secret Expiry (IST):</td><td style="padding: 8px;">{expires_on_ist_str}</td></tr>
            </table>
            <p><strong>NOTE: This new secret is valid for {'10 minute' if is_testing else '24 months'} from date of creation.</strong></p>
            <p><strong>Please discard the old secret and store these new credentials securely</strong>.</p>
            <p>Best Regards,<br>Azure Service Principal Automation Team</p>
          </body>
        </html>
        """
        try:
            msg = Message(
                subject=f"Secret Renewed: Azure Service Principal '{app_name}'",
                recipients=[email],
                html=email_body_html
            )
            self.mail.send(msg)
        except Exception as e:
            print(f"[ERROR] Failed to send renewal email: {e}")

        return {
            'message': f"Secret for '{app_name}' has been renewed. New credentials have been emailed to {email}.",
            'client_id': client_id,
            'tenant_id': tenant_id,
        }, 200

    # UPDATED: Completely rewritten to check the real latest secret in Azure
    def send_upcoming_expiry_notifications(self, days=30, resend_interval_days=2):
        """
        Checks Azure for the true latest secret expiry and sends notifications.
        Resends every `resend_interval_days` days if not renewed.
        """
        print(f"[INFO] Starting expiry notification check for {days} days.")
        expiring_secrets = self.user_service.get_expiring_secrets(days)
        notifications_sent = 0
        for secret in expiring_secrets:
            try:
                # Get user info
                user_info_id = secret['user_info_id']
                conn = self.db_config.connect()
                cursor = conn.cursor()
                cursor.execute("SELECT user_name, email FROM user_info WHERE id = ?", (user_info_id,))
                row = cursor.fetchone()
                if row:
                    user_name, email = row
                else:
                    continue
                conn.close()
                expires_str = secret['end_date'].strftime('%Y-%m-%d %H:%M:%S')
                email_body_html = f"""
                <html>
                  <body style="font-family: Arial, sans-serif; color: #333;">
                    <p>Hi {user_name},</p>
                    <p><strong>Heads up:</strong> Your Azure Service Principal secret for <strong>{secret['app_name']}</strong> will expire on <strong>{expires_str}</strong>.</p>
                    <p>Please renew it before expiry to avoid disruption.</p>
                    <p>Best Regards,<br>Azure Service Principal Automation Team</p>
                  </body>
                </html>
                """
                msg = Message(
                    subject=f"[Upcoming Expiry] SP Secret for '{secret['app_name']}'",
                    recipients=[email],
                    html=email_body_html
                )
                self.mail.send(msg)
                self.user_service.mark_secret_notified(secret['id'], column="notified_upcoming")
                notifications_sent += 1
            except Exception as e:
                print(f"[ERROR] Failed to process notifications for secret {secret['id']}: {e}")
        return {'message': f'Notification check complete. Sent {notifications_sent} notifications.'}, 200

    # NOTE: This method could also be updated with the new logic for consistency.
    def send_expired_notifications(self):
        expired_secrets = self.user_service.get_expired_secrets()
        if not expired_secrets:
            print("[INFO] No expired secrets found.")
            return {'message': 'No expired secrets found.'}, 200
        for secret in expired_secrets:
            try:
                user_info_id = secret['user_info_id']
                conn = self.db_config.connect()
                cursor = conn.cursor()
                cursor.execute("SELECT user_name, email FROM user_info WHERE id = ?", (user_info_id,))
                row = cursor.fetchone()
                if row:
                    user_name, email = row
                else:
                    continue
                conn.close()
                expires_str = secret['end_date'].strftime('%Y-%m-%d %H:%M:%S')
                email_body_html = f"""
                <html>
                    <body style="font-family: Arial, sans-serif; color: #333;">
                        <p>Hi {user_name},</p>
                        <p><strong>Action Required:</strong> Your Azure Service Principal secret for <strong>{secret['app_name']}</strong> expired on <strong>{expires_str}</strong>.</p>
                        <p>Please generate a new secret to avoid service disruption.</p>
                        <p>Best Regards,<br>Azure Service Principal Automation Team</p>
                    </body>
                </html>
                """
                msg = Message(
                    subject=f"[Expired] SP Secret for '{secret['app_name']}'",
                    recipients=[email],
                    html=email_body_html
                )
                self.mail.send(msg)
                self.user_service.mark_secret_notified(secret['id'], column="notified_expired")
                print(f"[DEBUG] Marked expired notification sent for: {secret['app_name']}")
            except Exception as e:
                print(f"[ERROR] Failed to send expired email to {secret['id']}: {e}")
        return {'message': f'Expired notifications sent to {len(expired_secrets)} user(s).'}, 200


