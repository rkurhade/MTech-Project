import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ConfigLoader:
    @staticmethod
    def load_db_config():
        return {
            'server': os.getenv('DB_SERVER'),
            'database': os.getenv('DB_DATABASE'),
            'username': os.getenv('DB_USERNAME'),
            'password': os.getenv('DB_PASSWORD')
        }

    @staticmethod
    def load_azure_ad_config():
        return {
            'client_id': os.getenv('CLIENT_ID'),
            'client_secret': os.getenv('CLIENT_SECRET'),
            'tenant_id': os.getenv('TENANT_ID')
        }

    @staticmethod
    def load_mail_config():
        return {
            "MAIL_SERVER": os.getenv("MAIL_SERVER"),
            "MAIL_PORT": int(os.getenv("MAIL_PORT", 587)),
            "MAIL_USERNAME": os.getenv("MAIL_USERNAME"),
            "MAIL_PASSWORD": os.getenv("MAIL_PASSWORD"),
            "MAIL_USE_TLS": os.getenv("MAIL_USE_TLS", "true").lower() == "true",
            "MAIL_USE_SSL": os.getenv("MAIL_USE_SSL", "false").lower() == "true",
            "MAIL_DEFAULT_SENDER": os.getenv("MAIL_DEFAULT_SENDER")
        }