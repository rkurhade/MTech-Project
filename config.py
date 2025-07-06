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
