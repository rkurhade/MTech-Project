# app.py
from flask import Flask, render_template, request, jsonify
from config import ConfigLoader
from clients import AzureADClient
from services import DatabaseConfig, UserService
from controllers import AppController
from flask_mail import Mail
from dotenv import load_dotenv
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


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)