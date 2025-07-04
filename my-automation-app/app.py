from flask import Flask, render_template, request, jsonify
from config import ConfigLoader
from clients import AzureADClient
from services import DatabaseConfig, UserService
from controllers import AppController
from flask_mail import Mail, Message
import os
import re
from dotenv import load_dotenv

load_dotenv()

# Setup Flask app
app = Flask(__name__)

# Configure mail settings from .env
app.config.update(
    MAIL_SERVER=os.getenv("MAIL_SERVER"),
    MAIL_PORT=int(os.getenv("MAIL_PORT")),
    MAIL_USE_TLS=os.getenv("MAIL_USE_TLS") == "True",
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER")
)
mail = Mail(app)

# Load services and controller
db_config = DatabaseConfig(ConfigLoader.load_db_config())
azure_ad_client = AzureADClient(ConfigLoader.load_azure_ad_config())
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

    # ✅ Backend email format validation
    if not EMAIL_REGEX.match(email.lower()):
        return jsonify({'error': 'Invalid email format provided.'}), 400

    response, status_code = app_controller.create_application(user_name, email, app_name)
    return jsonify(response), status_code


#if __name__ == '__main__':
#    app.run(host='0.0.0.0', port=5000, debug=True)

#if __name__ == '__main__':
#    app.run()

#if __name__ == '__main__':
 #   app.run(debug=True)


if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 8000))  # Azure sets this
    app.run(host='0.0.0.0', port=port)