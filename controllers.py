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

    def _create_email_template(self, template_type, user_name, app_name, **kwargs):
        """
        Unified email template generator with shared styling.
        template_type: 'creation', 'renewal', 'expiry', 'expired'
        """
        base_style = "font-family: Arial, sans-serif; color: #333; line-height: 1.6;"
        table_style = "border-collapse: collapse; margin-top: 10px;"
        cell_style = "padding: 8px;"
        bold_cell_style = "padding: 8px; font-weight: bold;"
        
        if template_type == 'creation':
            client_id = kwargs['client_id']
            client_secret = kwargs['client_secret']
            tenant_id = kwargs['tenant_id']
            expires_str = kwargs['expires_str']
            is_testing = kwargs['is_testing']
            
            return f"""
            <html>
              <body style="{base_style}">
                <p>Hi {user_name},</p>
                <p>Your Azure Service Principal has been created successfully. Please find the credentials below:</p>
                <table style="{table_style}">
                  <tr><td style="{bold_cell_style}">Service Principal Name:</td><td style="{cell_style}">{app_name}</td></tr>
                  <tr><td style="{bold_cell_style}">Client ID:</td><td style="{cell_style}">{client_id}</td></tr>
                  <tr><td style="{bold_cell_style}">Client Secret:</td><td style="{cell_style}">{client_secret}</td></tr>
                  <tr><td style="{bold_cell_style}">Tenant ID:</td><td style="{cell_style}">{tenant_id}</td></tr>
                  <tr><td style="{bold_cell_style}">Secret Expiry (IST):</td><td style="{cell_style}">{expires_str}</td></tr>
                </table>
                <p><strong>NOTE: Secret is valid for {'10 minute' if is_testing else '24 months'} from date of creation</strong>.</p>
                <p><strong>Please store these credentials securely</strong>. Do not share them with unauthorized users.</p>
                <p>Best Regards,<br>Azure Service Principal Automation Team</p>
              </body>
            </html>
            """
        
        elif template_type == 'renewal':
            client_id = kwargs['client_id']
            new_secret = kwargs['new_secret']
            tenant_id = kwargs['tenant_id']
            expires_str = kwargs['expires_str']
            is_testing = kwargs['is_testing']
            
            return f"""
            <html>
              <body style="{base_style}">
                <p>Hi {user_name},</p>
                <p>The client secret for your Azure Service Principal <strong>'{app_name}'</strong> has been successfully renewed.</p>
                <p>Please find the new credentials below:</p>
                <table style="{table_style}">
                  <tr><td style="{bold_cell_style}">Service Principal Name:</td><td style="{cell_style}">{app_name}</td></tr>
                  <tr><td style="{bold_cell_style}">Client ID:</td><td style="{cell_style}">{client_id}</td></tr>
                  <tr><td style="{bold_cell_style}">New Client Secret:</td><td style="{cell_style}">{new_secret}</td></tr>
                  <tr><td style="{bold_cell_style}">Tenant ID:</td><td style="{cell_style}">{tenant_id}</td></tr>
                  <tr><td style="{bold_cell_style}">New Secret Expiry (IST):</td><td style="{cell_style}">{expires_str}</td></tr>
                </table>
                <p><strong>NOTE: This new secret is valid for {'10 minute' if is_testing else '24 months'} from date of creation.</strong></p>
                <p><strong>Please discard the old secret and store these new credentials securely</strong>.</p>
                <p>Best Regards,<br>Azure Service Principal Automation Team</p>
              </body>
            </html>
            """
        
        elif template_type == 'expiry':
            expires_str = kwargs['expires_str']
            
            return f"""
            <html>
              <body style="{base_style}">
                <p>Hi {user_name},</p>
                <p><strong>Heads up:</strong> Your Azure Service Principal secret for <strong>{app_name}</strong> will expire on <strong>{expires_str}</strong>.</p>
                <p>Please renew it before expiry to avoid disruption.</p>
                <p>Best Regards,<br>Azure Service Principal Automation Team</p>
              </body>
            </html>
            """
        
        elif template_type == 'expired':
            expires_str = kwargs['expires_str']
            
            return f"""
            <html>
                <body style="{base_style}">
                    <p>Hi {user_name},</p>
                    <p><strong>Action Required:</strong> Your Azure Service Principal secret for <strong>{app_name}</strong> expired on <strong>{expires_str}</strong>.</p>
                    <p>Please generate a new secret to avoid service disruption.</p>
                    <p>Best Regards,<br>Azure Service Principal Automation Team</p>
                </body>
            </html>
            """

    def _send_email(self, subject, recipients, html_body):
        """Helper method to send emails with error handling."""
        try:
            msg = Message(subject=subject, recipients=recipients, html=html_body)
            self.mail.send(msg)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send email: {e}")
            return False

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

        # Check if Application Registration exists
        existing_app = self.azure_ad_client.search_application(token, app_name)
        if existing_app:
            print("[ERROR] Application Registration already exists:", app_name)
            return {
                'error': f"Application Registration with name '{app_name}' already exists.",
                'app_id': existing_app['id'],
                'client_id': existing_app['appId']
            }, 409

        # Check if Service Principal (Enterprise Application) exists
        existing_sp = self.azure_ad_client.search_service_principal(token, app_name)
        if existing_sp:
            print("[ERROR] Service Principal already exists:", app_name)
            return {
                'error': f"Service Principal (Enterprise Application) with name '{app_name}' already exists.",
                'sp_id': existing_sp['id'],
                'app_id': existing_sp['appId']
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


        # Prepare secret_info for app_secrets
        # Prepare secret_info for app_secrets
        secret_info = {
            'key_id': 'initial',  # You may want to fetch the real key_id from Azure response
            'end_date': expires_on,
            'display_name': f"{app_name} - New Secret"
        }
        success = self.user_service.store_user_and_secret(user_name, email, app_name, secret_info)
        if not success:
            print("[ERROR] Failed to store user and secret data.")
            self.azure_ad_client.delete_application(token, client_id)
            return {'error': 'Failed to store user/secret data in the database.'}, 500

        tenant_id = self.azure_ad_client.tenant_id
        ist = pytz.timezone("Asia/Kolkata")
        expires_on_ist_str = expires_on.astimezone(ist).strftime('%Y-%m-%d %H:%M:%S')

        # Create and send email using template helper
        html_body = self._create_email_template(
            'creation', user_name, app_name,
            client_id=client_id, client_secret=client_secret, tenant_id=tenant_id,
            expires_str=expires_on_ist_str, is_testing=is_testing
        )
        
        success = self._send_email(
            f"Azure Service Principal Credentials for '{app_name}'",
            [email],
            html_body
        )
        
        if not success:
            return {'error': 'Failed to send email notification.'}, 500

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

        # Prepare secret_info for app_secrets
        secret_info = {
            'key_id': 'renewed',  # You may want to fetch the real key_id from Azure response
            'end_date': new_expiry_date,
            'display_name': f"{app_name} - Secret Renewed"
        }
        success = self.user_service.add_new_secret(app_name, secret_info)
        if not success:
            print(f"[ERROR] Could not update local DB for app: {app_name}")
            return {'error': 'Secret created in Azure, but could not update local database. Please contact support.'}, 500

        # Get user details for email using the helper method
        latest_secret = self.user_service.get_latest_secret(app_name)
        if not latest_secret:
            return {'error': 'Could not find user information for notification.'}, 500
            
        user_info = self.user_service.get_user_info_by_id(latest_secret['user_info_id'])
        if not user_info:
            return {'error': 'Could not find user information for notification.'}, 500

        tenant_id = self.azure_ad_client.tenant_id
        expires_on_ist_str = new_expiry_date.astimezone(self.ist).strftime('%Y-%m-%d %H:%M:%S')

        # Create and send email using template helper
        html_body = self._create_email_template(
            'renewal', user_info['user_name'], app_name,
            client_id=client_id, new_secret=new_secret, tenant_id=tenant_id,
            expires_str=expires_on_ist_str, is_testing=is_testing
        )
        
        success = self._send_email(
            f"Secret Renewed: Azure Service Principal '{app_name}'",
            [user_info['email']],
            html_body
        )
        
        if not success:
            print(f"[ERROR] Failed to send renewal email to {user_info['email']}")

        return {
            'message': f"Secret for '{app_name}' has been renewed. New credentials have been emailed to {user_info['email']}.",
            'client_id': client_id,
            'tenant_id': tenant_id,
        }, 200

    # UPDATED: Completely rewritten to check the real latest secret in Azure
    def send_upcoming_expiry_notifications(self, days=30, resend_interval_days=2):
        """
        Checks Azure for the true latest secret expiry and sends notifications.
        Resends every `resend_interval_days` days if not renewed.
        """
        print(f"[INFO] Starting expiry notification check for {days} days with {resend_interval_days}-day resend interval.")
        expiring_secrets = self.user_service.get_expiring_secrets(days, resend_interval_days)
        notifications_sent = 0
        
        for secret in expiring_secrets:
            try:
                # Get user info using helper method
                user_info = self.user_service.get_user_info_by_id(secret['user_info_id'])
                if not user_info:
                    continue
                
                expires_str = secret['end_date'].strftime('%Y-%m-%d %H:%M:%S')
                
                # Create email using template helper
                html_body = self._create_email_template(
                    'expiry', user_info['user_name'], secret['app_name'],
                    expires_str=expires_str
                )
                
                success = self._send_email(
                    f"[Upcoming Expiry] SP Secret for '{secret['app_name']}'",
                    [user_info['email']],
                    html_body
                )
                
                if success:
                    self.user_service.mark_secret_notified(secret['id'], column="notified_upcoming")
                    notifications_sent += 1
                    print(f"[INFO] Sent upcoming expiry notification for {secret['app_name']} to {user_info['email']}")
                    
            except Exception as e:
                print(f"[ERROR] Failed to process notifications for secret {secret['id']}: {e}")
                
        return {'message': f'Notification check complete. Sent {notifications_sent} notifications.'}, 200

    def send_expired_notifications(self, resend_interval_days=2):
        """
        Sends notifications for expired secrets with configurable resend interval.
        """
        print(f"[INFO] Starting expired secrets notification check with {resend_interval_days}-day resend interval.")
        expired_secrets = self.user_service.get_expired_secrets(resend_interval_days)
        if not expired_secrets:
            print("[INFO] No expired secrets found.")
            return {'message': 'No expired secrets found.'}, 200
            
        for secret in expired_secrets:
            try:
                # Get user info using helper method
                user_info = self.user_service.get_user_info_by_id(secret['user_info_id'])
                if not user_info:
                    continue
                
                expires_str = secret['end_date'].strftime('%Y-%m-%d %H:%M:%S')
                
                # Create email using template helper
                html_body = self._create_email_template(
                    'expired', user_info['user_name'], secret['app_name'],
                    expires_str=expires_str
                )
                
                success = self._send_email(
                    f"[Expired] SP Secret for '{secret['app_name']}'",
                    [user_info['email']],
                    html_body
                )
                
                if success:
                    self.user_service.mark_secret_notified(secret['id'], column="notified_expired")
                    print(f"[INFO] Sent expired notification for {secret['app_name']} to {user_info['email']}")
                    
            except Exception as e:
                print(f"[ERROR] Failed to send expired email to {secret['id']}: {e}")
                
        return {'message': f'Expired notifications sent to {len(expired_secrets)} user(s).'}, 200

    def generate_monthly_report(self, year=None, month=None, send_email=True, admin_email="azurespnautomation@gmail.com", output_format="html"):
        """
        Generates monthly Service Principal creation report in HTML or email format.
        
        Args:
            year: Report year (defaults to previous month)
            month: Report month (defaults to previous month)  
            send_email: Whether to send email (default: True)
            admin_email: Email recipient for reports
            output_format: 'html' for standalone HTML file, 'email' for email HTML
        """
        try:
            print(f"[DEBUG] generate_monthly_report called with year={year}, month={month}, send_email={send_email}, output_format={output_format}")
            
            # Use previous month if no specific month provided
            if year is None or month is None:
                print("[DEBUG] Using previous month report")
                report_data = self.user_service.get_previous_month_report()
            else:
                print(f"[DEBUG] Using specific month: {year}-{month}")
                report_data = self.user_service.get_monthly_report_data(year, month)
            
            if not report_data:
                print("[ERROR] report_data is None or empty")
                return {'error': 'Failed to generate report data'}, 500
            
            summary = report_data['summary']
            details = report_data['details']
            
            # Month names for better formatting
            month_names = {
                1: 'January', 2: 'February', 3: 'March', 4: 'April',
                5: 'May', 6: 'June', 7: 'July', 8: 'August',
                9: 'September', 10: 'October', 11: 'November', 12: 'December'
            }
            
            month_name = month_names.get(summary['month'], str(summary['month']))
            report_period = f"{month_name} {summary['year']}"
            
            # Generate HTML report using template
            if output_format == "html":
                return self._generate_html_report(summary, details, report_period)
            
            # Generate JSON format for API responses
            if output_format == "json":
                return {
                    'message': f'Monthly report data for {report_period}',
                    'report_data': {
                        'period': report_period,
                        'summary': summary,
                        'details': [
                            {
                                'created_date': detail['created_date'].strftime('%Y-%m-%d'),
                                'user_name': detail['user_name'],
                                'email': detail['email'],
                                'app_name': detail['app_name']
                            } for detail in details
                        ] if details else []
                    }
                }, 200
            
            # Generate email HTML (legacy format)
            details_html = ""
            if details:
                details_html = """
                <h3>📋 Detailed List:</h3>
                <table style="border-collapse: collapse; width: 100%; margin-top: 10px;">
                    <thead>
                        <tr style="background-color: #f0f0f0;">
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Date</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">User Name</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Email</th>
                            <th style="border: 1px solid #ddd; padding: 8px; text-align: left;">Service Principal Name</th>
                        </tr>
                    </thead>
                    <tbody>
                """
                
                for detail in details:
                    created_date_str = detail['created_date'].strftime('%Y-%m-%d')
                    details_html += f"""
                        <tr>
                            <td style="border: 1px solid #ddd; padding: 8px;">{created_date_str}</td>
                            <td style="border: 1px solid #ddd; padding: 8px;">{detail['user_name']}</td>
                            <td style="border: 1px solid #ddd; padding: 8px;">{detail['email']}</td>
                            <td style="border: 1px solid #ddd; padding: 8px;">{detail['app_name']}</td>
                        </tr>
                    """
                
                details_html += """
                    </tbody>
                </table>
                """
            else:
                details_html = "<p>🔹 No Service Principals were created during this period.</p>"
            
            email_body_html = f"""
            <html>
              <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
                <div style="max-width: 800px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #0078d4; border-bottom: 2px solid #0078d4; padding-bottom: 10px;">
                        📊 Azure Service Principal Monthly Report
                    </h2>
                    
                    <h3>📅 Report Period: {report_period}</h3>
                    
                    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #0078d4;">📈 Summary Statistics</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Total Service Principals Created:</strong></td>
                                <td style="padding: 8px; border-bottom: 1px solid #ddd; color: #0078d4; font-weight: bold;">{summary['total_created']}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>Unique Users:</strong></td>
                                <td style="padding: 8px; border-bottom: 1px solid #ddd;">{summary['unique_users']}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px;"><strong>Unique Email Addresses:</strong></td>
                                <td style="padding: 8px;">{summary['unique_emails']}</td>
                            </tr>
                        </table>
                    </div>
                    
                    {details_html}
                    
                    <div style="margin-top: 30px; padding: 15px; background-color: #e8f4fd; border-radius: 5px;">
                        <p style="margin: 0;"><strong>📧 Report generated on:</strong> {datetime.now(pytz.timezone("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')} IST</p>
                        <p style="margin: 5px 0 0 0;"><small>This is an automated report from Azure Service Principal Management System.</small></p>
                    </div>
                </div>
              </body>
            </html>
            """
            
            if send_email:
                try:
                    print(f"[DEBUG] Attempting to send email to {admin_email}")
                    print(f"[DEBUG] Email settings - Server: {self.mail.app.config.get('MAIL_SERVER')}, Port: {self.mail.app.config.get('MAIL_PORT')}")
                    from flask_mail import Message
                    msg = Message(
                        subject=f"📊 Monthly SPN Report - {report_period} ({summary['total_created']} Created)",
                        recipients=[admin_email],
                        html=email_body_html
                    )
                    print(f"[DEBUG] Email message created for {admin_email}, subject: {msg.subject}")
                    print("[DEBUG] Attempting to send via Flask-Mail...")
                    self.mail.send(msg)
                    print(f"[SUCCESS] Monthly report sent successfully to {admin_email}")
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    print(f"[ERROR] Failed to send monthly report email: {e}")
                    print(f"[ERROR] Full traceback: {error_details}")
                    # Still return success if report was generated, just mention email failed
                    return {
                        'error': f'Report generated successfully but failed to send email: {str(e)}',
                        'report_data': {
                            'period': report_period,
                            'summary': summary,
                            'total_apps': len(details)
                        },
                        'email_error_details': str(e)
                    }, 500
            
            return {
                'message': f'Monthly report for {report_period} generated successfully.',
                'report_data': {
                    'period': report_period,
                    'summary': summary,
                    'total_apps': len(details)
                },
                'email_sent': send_email
            }, 200
            
        except Exception as e:
            print(f"[ERROR] Failed to generate monthly report: {e}")
            return {'error': f'Failed to generate monthly report: {str(e)}'}, 500

    def _generate_html_report(self, summary, details, report_period):
        """
        Generates standalone HTML report using Jinja2 template.
        """
        try:
            from flask import render_template
            import os
            from datetime import datetime
            
            # Generate HTML content
            html_content = render_template('monthly_report.html', 
                summary=summary,
                details=details,
                report_period=report_period,
                generated_date=datetime.now(pytz.timezone("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S IST')
            )
            
            # Save HTML file
            filename = f"SPN_Monthly_Report_{summary['year']}_{summary['month']:02d}.html"
            filepath = os.path.join(os.getcwd(), 'reports', filename)
            
            # Create reports directory if it doesn't exist
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            return {
                'message': f'HTML report generated successfully for {report_period}.',
                'report_data': {
                    'period': report_period,
                    'summary': summary,
                    'total_apps': len(details)
                },
                'html_file': filepath,
                'filename': filename,
                'html_content': html_content  # For API response
            }, 200
            
        except Exception as e:
            print(f"[ERROR] Failed to generate HTML report: {e}")
            return {'error': f'Failed to generate HTML report: {str(e)}'}, 500
