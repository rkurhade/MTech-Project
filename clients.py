# clients.py
import requests
import os
from datetime import datetime # NEW: Import for creating unique secret names

class AzureADClient:
    def __init__(self, config):
        self.client_id = config['client_id']
        self.client_secret = config['client_secret']
        self.tenant_id = config['tenant_id']
        self.authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.graph_endpoint = 'https://graph.microsoft.com/v1.0'
        self.mock = os.getenv("MOCK_MODE", "false").lower() == "true"

    def get_access_token(self):
        if self.mock:
            print("[MOCK] Returning dummy token")
            return "mock_token"

        url = f'{self.authority}/oauth2/v2.0/token'
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = {
            'client_id': self.client_id,
            'scope': 'https://graph.microsoft.com/.default',
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials'
        }

        response = requests.post(url, headers=headers, data=data)
        if response.ok:
            return response.json().get('access_token')
        print(f"[ERROR] Failed to get access token: {response.status_code} - {response.text}")
        return None

    def search_application(self, token, app_name):
        if self.mock:
            print(f"[MOCK] No app found for name: {app_name}")
            return None

        url = f"{self.graph_endpoint}/applications?$filter=displayName eq '{app_name}'"

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data['value']:
                return data['value'][0]  # Return the first matching app
            return None
        except requests.exceptions.RequestException as err:
            print(f"[ERROR] Failed to search application: {err}")
        return None

    def create_application(self, token, app_name):
        if self.mock:
            print(f"[MOCK] Creating fake app: {app_name}")
            return f"mock-client-id-{app_name}", f"mock-secret-{app_name}"

        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        app_data = {"displayName": app_name}

        response = requests.post(f"{self.graph_endpoint}/applications", headers=headers, json=app_data)
        if not response.ok:
            print(f"[ERROR] Failed to create Azure app '{app_name}': {response.status_code} - {response.text}")
            return None, None

        app = response.json()
        app_id = app.get('id')
        client_id = app.get('appId')

        secret_data = {"passwordCredential": {"displayName": f"{app_name} secret"}}
        secret_response = requests.post(f"{self.graph_endpoint}/applications/{app_id}/addPassword", headers=headers, json=secret_data)
        if secret_response.ok:
            client_secret = secret_response.json().get('secretText')
            return client_id, client_secret

        print(f"[ERROR] Failed to create secret: {secret_response.status_code} - {secret_response.text}")
        return None, None

    def delete_application(self, token, client_id):
        if self.mock:
            print(f"[MOCK] Deleting fake app: {client_id}")
            return True

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        search_url = f"{self.graph_endpoint}/applications?$filter=appId eq '{client_id}'"
        search_response = requests.get(search_url, headers=headers)

        if not search_response.ok:
            print(f"[ERROR] Failed to find app for deletion: {search_response.status_code} - {search_response.text}")
            return False

        apps = search_response.json().get('value', [])
        if not apps:
            print("[INFO] No service principal found to delete.")
            return False

        app_object_id = apps[0]['id']
        delete_url = f"{self.graph_endpoint}/applications/{app_object_id}"
        delete_response = requests.delete(delete_url, headers=headers)

        if delete_response.status_code == 204:
            print("[INFO] Service principal deleted successfully.")
            return True
        else:
            print(f"[ERROR] Failed to delete app: {delete_response.status_code} - {delete_response.text}")
            return False

    def add_owner_to_application(self, token, app_id, user_email):
        """
        Adds the given user email as an owner to the Azure AD app.
        Tries both /users/{user_email} and /users?$filter=mail eq '{user_email}'.
        Prints full error responses for easier debugging.
        """
        if self.mock:
            print(f"[MOCK] Adding {user_email} as owner to app {app_id}")
            return True

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Try /users/{user_email} first
        url_user = f"{self.graph_endpoint}/users/{user_email}"
        resp_user = requests.get(url_user, headers=headers)
        if resp_user.ok:
            user_id = resp_user.json().get('id')
        else:
            print(f"[WARN] /users/{{user_email}} failed: {resp_user.status_code} {resp_user.text}")
            # Try /users?$filter=mail eq '{user_email}'
            url_user2 = f"{self.graph_endpoint}/users?$filter=mail eq '{user_email}'"
            resp_user2 = requests.get(url_user2, headers=headers)
            if resp_user2.ok:
                users = resp_user2.json().get('value', [])
                if users:
                    user_id = users[0].get('id')
                else:
                    print(f"[ERROR] No user found with mail eq '{user_email}'. Response: {resp_user2.text}")
                    return False
            else:
                print(f"[ERROR] /users?$filter=mail eq failed: {resp_user2.status_code} {resp_user2.text}")
                return False

        # Add owner
        url_owner = f"{self.graph_endpoint}/applications/{app_id}/owners/$ref"
        body = {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"}
        resp_owner = requests.post(url_owner, headers=headers, json=body)
        if resp_owner.status_code not in (200, 204):
            print(f"[ERROR] Failed to add owner {user_email}: {resp_owner.status_code} {resp_owner.text}")
            return False

        print(f"[INFO] Added {user_email} as owner to application {app_id}")
        return True

    # NEW: Method to add a new secret to an existing application (for renewal)
    def add_password_to_application(self, token, app_object_id, app_name):
        """
        Adds a new password (client secret) to an existing Azure AD application.
        """
        if self.mock:
            print(f"[MOCK] Adding new secret to existing app: {app_name}")
            return f"mock-new-secret-{app_name}"

        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        # Using a unique display name for the new secret
        secret_display_name = f"{app_name} secret - {datetime.now().strftime('%Y-%m-%d')}"
        secret_data = {"passwordCredential": {"displayName": secret_display_name}}
        
        url = f"{self.graph_endpoint}/applications/{app_object_id}/addPassword"
        secret_response = requests.post(url, headers=headers, json=secret_data)
        
        if secret_response.ok:
            client_secret = secret_response.json().get('secretText')
            return client_secret

        print(f"[ERROR] Failed to add new password: {secret_response.status_code} - {secret_response.text}")
        return None

    # NEW: Method to get an application's details including all its secrets
    def get_application_with_secrets(self, token, app_name):
        """
        Searches for an application and returns its details, including passwordCredentials.
        """
        if self.mock:
            print(f"[MOCK] Returning fake app with secrets for: {app_name}")
            mock_end_date = (datetime.now() + timedelta(days=30)).isoformat() + "Z"
            return {
                "id": f"mock-id-{app_name}",
                "displayName": app_name,
                "passwordCredentials": [{"endDateTime": mock_end_date, "keyId": "mock-key-id"}]
            }

        # The $select parameter is crucial for efficiency
        url = f"{self.graph_endpoint}/applications?$filter=displayName eq '{app_name}'&$select=id,displayName,passwordCredentials"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data['value']:
                return data['value'][0]  # Return the first matching app with its secrets
            return None
        except requests.exceptions.RequestException as err:
            print(f"[ERROR] Failed to get application with secrets: {err}")
        return None