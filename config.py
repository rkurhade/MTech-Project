import os

class ConfigLoader:
    _db_config = None
    _azure_ad_config = None
    _mail_config = None

    @staticmethod
    def load_db_config():
        if ConfigLoader._db_config is None:
            config = {
                'server': os.getenv('DB_SERVER'),
                'database': os.getenv('DB_DATABASE'),
                'username': os.getenv('DB_USERNAME'),
                'password': os.getenv('DB_PASSWORD')
            }
            # Basic validation example
            missing = [k for k, v in config.items() if not v]
            if missing:
                raise EnvironmentError(f"Missing DB config env vars: {missing}")
            ConfigLoader._db_config = config
        return ConfigLoader._db_config

    @staticmethod
    def load_azure_ad_config():
        if ConfigLoader._azure_ad_config is None:
            config = {
                'client_id': os.getenv('CLIENT_ID'),
                'client_secret': os.getenv('CLIENT_SECRET'),
                'tenant_id': os.getenv('TENANT_ID')
            }
            missing = [k for k, v in config.items() if not v]
            if missing:
                raise EnvironmentError(f"Missing Azure AD config env vars: {missing}")
            ConfigLoader._azure_ad_config = config
        return ConfigLoader._azure_ad_config

    @staticmethod
    def load_mail_config():
        if ConfigLoader._mail_config is None:
            config = {
                "MAIL_SERVER": os.getenv("MAIL_SERVER"),
                "MAIL_PORT": int(os.getenv("MAIL_PORT", 587)),
                "MAIL_USERNAME": os.getenv("MAIL_USERNAME"),
                "MAIL_PASSWORD": os.getenv("MAIL_PASSWORD"),
                "MAIL_USE_TLS": os.getenv("MAIL_USE_TLS", "true").lower() == "true",
                "MAIL_USE_SSL": os.getenv("MAIL_USE_SSL", "false").lower() == "true",
                "MAIL_DEFAULT_SENDER": os.getenv("MAIL_DEFAULT_SENDER")
            }
            missing = [k for k, v in config.items() if v is None and k != "MAIL_DEFAULT_SENDER"]
            if missing:
                raise EnvironmentError(f"Missing Mail config env vars: {missing}")
            ConfigLoader._mail_config = config
        return ConfigLoader._mail_config