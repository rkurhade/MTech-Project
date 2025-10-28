# app.py
from flask import Flask, render_template, request, jsonify
from config import ConfigLoader
from clients import AzureADClient
from services import DatabaseConfig, UserService
from controllers import AppController
from flask_mail import Mail
from dotenv import load_dotenv
from datetime import datetime
import re
import os

load_dotenv()  # Load local .env variables only for local testing

app = Flask(__name__)

# Load mail config from ConfigLoader
mail_config = ConfigLoader.load_mail_config()

app.config.update(
    MAIL_SERVER=mail_config['MAIL_SERVER'],
    MAIL_PORT=mail_config['MAIL_PORT'],
    MAIL_USE_TLS=mail_config['MAIL_USE_TLS'],
    MAIL_USE_SSL=mail_config['MAIL_USE_SSL'],
    MAIL_USERNAME=mail_config['MAIL_USERNAME'],
    MAIL_PASSWORD=mail_config['MAIL_PASSWORD'],
    MAIL_DEFAULT_SENDER=mail_config['MAIL_DEFAULT_SENDER']
)

mail = Mail(app)

# Load other services and controller
db_config = DatabaseConfig(ConfigLoader.load_db_config())
azure_ad_client = AzureADClient(ConfigLoader.load_azure_ad_config())
# UserService now supports new DB structure
user_service = UserService(db_config)
app_controller = AppController(db_config, azure_ad_client, user_service, mail)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/debug/test_db')
def test_database():
    """Debug endpoint to test database connectivity for reports."""
    try:
        success = user_service.test_database_connection()
        return jsonify({
            'database_test': 'passed' if success else 'failed',
            'message': 'Check server logs for detailed debug information'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/test_email')
def test_email():
    """Debug endpoint to test email configuration."""
    try:
        test_email = request.args.get('email', 'test@example.com')
        from flask_mail import Message
        msg = Message(
            subject="🔧 Email Test from Azure SPN System",
            recipients=[test_email],
            html="""
            <html>
              <body style="font-family: Arial, sans-serif;">
                <h2>Email Test Successful! ✅</h2>
                <p>This is a test email from your Azure Service Principal Management System.</p>
                <p>If you received this email, your email configuration is working correctly.</p>
                <p><strong>Timestamp:</strong> {}</p>
              </body>
            </html>
            """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        mail.send(msg)
        return jsonify({
            'email_test': 'passed',
            'message': f'Test email sent successfully to {test_email}',
            'mail_config': {
                'server': app.config.get('MAIL_SERVER'),
                'port': app.config.get('MAIL_PORT'),
                'use_tls': app.config.get('MAIL_USE_TLS'),
                'username': app.config.get('MAIL_USERNAME')
            }
        })
    except Exception as e:
        return jsonify({
            'email_test': 'failed', 
            'error': str(e),
            'mail_config': {
                'server': app.config.get('MAIL_SERVER'),
                'port': app.config.get('MAIL_PORT'),
                'use_tls': app.config.get('MAIL_USE_TLS'),
                'username': app.config.get('MAIL_USERNAME')
            }
        }), 500

EMAIL_REGEX = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")

@app.route('/create_app', methods=['POST'])
def create_app():
    data = request.json
    user_name = data.get('user_name')
    email = data.get('user_email')
    app_name = data.get('app_name')

    if not email or not EMAIL_REGEX.match(email.lower()):
        return jsonify({'error': 'Invalid email format provided.'}), 400

    response, status_code = app_controller.create_application(user_name, email, app_name)
    return jsonify(response), status_code

# NEW: Route to renew a secret for an existing application
@app.route('/renew_app_secret', methods=['POST'])
def renew_secret():
    data = request.json
    app_name = data.get('app_name')

    if not app_name:
        return jsonify({'error': 'Application name is required.'}), 400

    response, status_code = app_controller.renew_application_secret(app_name)
    return jsonify(response), status_code

# UPDATED: Now uses a 2-day resend interval by default
@app.route('/notify_expiry', methods=['POST'])
def notify_expiry():
    try:
        days_before_expiry = int(request.args.get('days', 30))
        # The resend interval is now 2 days as per your requirement
        response, status = app_controller.send_upcoming_expiry_notifications(days_before_expiry, resend_interval_days=2)
        return jsonify(response), status
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/notify_expired', methods=['POST'])
def notify_expired():
    try:
        # Use a 2-day resend interval by default, matching the upcoming expiry notifications
        response, status = app_controller.send_expired_notifications(resend_interval_days=2)
        return jsonify(response), status
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/monthly_report', methods=['POST', 'GET'])
def generate_monthly_report():
    """
    Generate monthly Service Principal creation report.
    POST: Send email report
    GET: Return JSON report data
    
    Query parameters:
    - year: specific year (optional, defaults to previous month)
    - month: specific month (optional, defaults to previous month)  
    - admin_email: email to send report to (optional, defaults to azurespnautomation@gmail.com)
    """
    try:
        # Get parameters
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        admin_email = request.args.get('admin_email', 'azurespnautomation@gmail.com')
        
        # Send email for POST, return JSON for GET
        send_email = (request.method == 'POST')
        
        response, status = app_controller.generate_monthly_report(
            year=year, 
            month=month, 
            send_email=send_email, 
            admin_email=admin_email
        )
        return jsonify(response), status
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/current_month_report', methods=['GET'])
def current_month_report():
    """
    Get current month Service Principal creation statistics (JSON only).
    """
    try:
        # Get current month data specifically
        from datetime import datetime
        now = datetime.now()
        response, status = app_controller.generate_monthly_report(
            year=now.year, 
            month=now.month, 
            send_email=False,
            output_format="json"
        )
        return jsonify(response), status
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/html_report', methods=['GET'])
def generate_html_report():
    """
    Generate standalone HTML report file.
    
    Query parameters:
    - year: specific year (optional, defaults to previous month)
    - month: specific month (optional, defaults to previous month)
    """
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        
        response, status = app_controller.generate_monthly_report(
            year=year, 
            month=month, 
            send_email=False,
            output_format="html"
        )
        return jsonify(response), status
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/view_report', methods=['GET'])
def view_html_report():
    """
    Generate and directly display HTML report in browser.
    
    Query parameters:
    - year: specific year (optional, defaults to previous month)
    - month: specific month (optional, defaults to previous month)
    """
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        
        response, status = app_controller.generate_monthly_report(
            year=year, 
            month=month, 
            send_email=False,
            output_format="html"
        )
        
        if status == 200 and 'html_content' in response:
            return response['html_content']
        else:
            return f"<h1>Error generating report</h1><p>{response.get('error', 'Unknown error')}</p>", status
    except Exception as e:
        return f"<h1>Error</h1><p>{str(e)}</p>", 500

@app.route('/download_report/<filename>')
def download_report(filename):
    """
    Download generated HTML report file.
    """
    try:
        import os
        from flask import send_file
        
        # Security check - only allow HTML files with expected naming pattern
        if not filename.endswith('.html') or not filename.startswith('SPN_Monthly_Report_'):
            return jsonify({'error': 'Invalid file name'}), 400
            
        filepath = os.path.join(os.getcwd(), 'reports', filename)
        
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True, download_name=filename)
        else:
            return jsonify({'error': 'Report file not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)