# clients.py
import requests
import os
from datetime import datetime, timedelta # NEW: Import for creating unique secret names

class AzureADClient:
    def __init__(self, config):
        self.client_id = config['client_id']
        self.client_secret = config['client_secret']
        self.tenant_id = config['tenant_id']
        self.authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.graph_endpoint = 'https://graph.microsoft.com/v1.0'
        self.mock = os.getenv("MOCK_MODE", "false").lower() == "true"

    def _make_request(self, method, url, headers, **kwargs):
        """
        Unified request helper with error handling.
        """
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            return response
        except requests.exceptions.RequestException as err:
            print(f"[ERROR] Request failed: {err}")
            return None

    def _delete_azure_resource(self, token, resource_type, resource_id):
        """
        Unified method to delete Azure resources (Application or Service Principal).
        resource_type: 'applications' or 'servicePrincipals'
        resource_id: object ID or search filter
        """
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # If resource_id contains '=' it's a search filter, otherwise it's a direct ID
        if '=' in resource_id:
            # Search first
            search_url = f"{self.graph_endpoint}/{resource_type}?$filter={resource_id}"
            search_response = self._make_request('GET', search_url, headers)
            
            if not search_response or not search_response.ok:
                print(f"[WARN] Failed to search for {resource_type}: {search_response.status_code if search_response else 'No response'}")
                return False

            resources = search_response.json().get('value', [])
            if not resources:
                print(f"[INFO] No {resource_type} found to delete.")
                return True  # Not an error if it doesn't exist

            object_id = resources[0]['id']
        else:
            object_id = resource_id

        # Delete the resource
        delete_url = f"{self.graph_endpoint}/{resource_type}/{object_id}"
        delete_response = self._make_request('DELETE', delete_url, headers)

        if delete_response and delete_response.status_code == 204:
            print(f"[INFO] {resource_type.rstrip('s').title()} deleted successfully: {object_id}")
            return True
        else:
            print(f"[ERROR] Failed to delete {resource_type}: {delete_response.status_code if delete_response else 'No response'}")
            return False

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
        
        response = self._make_request('GET', url, headers)
        if response and response.ok:
            data = response.json()
            return data['value'][0] if data['value'] else None
        return None

    def search_service_principal(self, token, app_name):
        """
        Searches for a Service Principal (Enterprise Application) by display name.
        """
        if self.mock:
            print(f"[MOCK] No service principal found for name: {app_name}")
            return None

        url = f"{self.graph_endpoint}/servicePrincipals?$filter=displayName eq '{app_name}'"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        response = self._make_request('GET', url, headers)
        if response and response.ok:
            data = response.json()
            return data['value'][0] if data['value'] else None
        return None

    def create_application(self, token, app_name):
        if self.mock:
            print(f"[MOCK] Creating fake app: {app_name}")
            return f"mock-client-id-{app_name}", f"mock-secret-{app_name}"

        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        app_data = {"displayName": app_name}

        # Step 1: Create the Application Registration
        response = requests.post(f"{self.graph_endpoint}/applications", headers=headers, json=app_data)
        if not response.ok:
            print(f"[ERROR] Failed to create Azure app '{app_name}': {response.status_code} - {response.text}")
            return None, None

        app = response.json()
        app_id = app.get('id')
        client_id = app.get('appId')
        print(f"[INFO] Created Application Registration: {app_name} with Client ID: {client_id}")

        # Step 2: Create the Service Principal (Enterprise Application)
        sp_data = {"appId": client_id}
        sp_response = requests.post(f"{self.graph_endpoint}/servicePrincipals", headers=headers, json=sp_data)
        if not sp_response.ok:
            print(f"[ERROR] Failed to create Service Principal for '{app_name}': {sp_response.status_code} - {sp_response.text}")
            # If SP creation fails, we should clean up the application
            self._cleanup_application(token, app_id)
            return None, None
        
        sp = sp_response.json()
        sp_object_id = sp.get('id')
        print(f"[INFO] Created Service Principal (Enterprise App): {app_name} with Object ID: {sp_object_id}")

        # Step 3: Create the client secret
        secret_data = {"passwordCredential": {"displayName": f"{app_name} secret"}}
        secret_response = requests.post(f"{self.graph_endpoint}/applications/{app_id}/addPassword", headers=headers, json=secret_data)
        if secret_response.ok:
            client_secret = secret_response.json().get('secretText')
            print(f"[INFO] Created client secret for '{app_name}'")
            return client_id, client_secret

        print(f"[ERROR] Failed to create secret: {secret_response.status_code} - {secret_response.text}")
        # Clean up both SP and App if secret creation fails
        self._cleanup_service_principal(token, client_id)
        self._cleanup_application(token, app_id)
        return None, None

    def delete_application(self, token, client_id):
        """
        Deletes both the Service Principal (Enterprise App) and Application Registration.
        """
        if self.mock:
            print(f"[MOCK] Deleting fake app: {client_id}")
            return True

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Step 1: Delete Service Principal first
        sp_deleted = self._cleanup_service_principal(token, client_id)
        
        # Step 2: Delete Application Registration
        search_url = f"{self.graph_endpoint}/applications?$filter=appId eq '{client_id}'"
        search_response = requests.get(search_url, headers=headers)

        if not search_response.ok:
            print(f"[ERROR] Failed to find app for deletion: {search_response.status_code} - {search_response.text}")
            return sp_deleted  # Return SP deletion result if we can't find the app

        apps = search_response.json().get('value', [])
        if not apps:
            print("[INFO] No application registration found to delete.")
            return sp_deleted

        app_object_id = apps[0]['id']
        app_deleted = self._cleanup_application(token, app_object_id)
        
        if app_deleted and sp_deleted:
            print("[INFO] Both Service Principal and Application Registration deleted successfully.")
            return True
        elif app_deleted:
            print("[WARN] Application deleted but Service Principal deletion failed/skipped.")
            return True
        elif sp_deleted:
            print("[WARN] Service Principal deleted but Application deletion failed.")
            return False
        else:
            print("[ERROR] Failed to delete both Service Principal and Application.")
            return False

    def _cleanup_service_principal(self, token, client_id):
        """
        Helper method to delete Service Principal (Enterprise Application).
        """
        return self._delete_azure_resource(token, 'servicePrincipals', f"appId eq '{client_id}'")

    def _cleanup_application(self, token, app_object_id):
        """
        Helper method to delete Application Registration.
        """
        return self._delete_azure_resource(token, 'applications', app_object_id)

    def add_owner_to_application(self, token, app_id, user_email):
        """
        Adds the given user email as an owner to both the Azure AD Application and Service Principal.
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

        # Get user ID first
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

        # Add owner to Application Registration
        url_app_owner = f"{self.graph_endpoint}/applications/{app_id}/owners/$ref"
        body = {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"}
        resp_app_owner = requests.post(url_app_owner, headers=headers, json=body)
        app_owner_success = resp_app_owner.status_code in (200, 204)
        
        if not app_owner_success:
            print(f"[ERROR] Failed to add owner {user_email} to application: {resp_app_owner.status_code} {resp_app_owner.text}")

        # Get Service Principal ID and add owner there too
        sp_success = self._add_owner_to_service_principal(token, app_id, user_id, user_email, headers)
        
        if app_owner_success and sp_success:
            print(f"[INFO] Added {user_email} as owner to both Application and Service Principal")
            return True
        elif app_owner_success:
            print(f"[WARN] Added {user_email} as owner to Application but not Service Principal")
            return True  # At least the application ownership worked
        elif sp_success:
            print(f"[WARN] Added {user_email} as owner to Service Principal but not Application")
            return False  # This is more concerning
        else:
            print(f"[ERROR] Failed to add {user_email} as owner to both Application and Service Principal")
            return False

    def _add_owner_to_service_principal(self, token, app_id, user_id, user_email, headers):
        """
        Helper method to add owner to Service Principal by finding it via the application.
        """
        try:
            # We need to find the Service Principal using the Application's appId
            # First get the application to find its appId
            app_response = requests.get(f"{self.graph_endpoint}/applications/{app_id}", headers=headers)
            if not app_response.ok:
                print(f"[WARN] Could not retrieve application details for Service Principal ownership")
                return False
                
            app_data = app_response.json()
            client_id = app_data.get('appId')
            
            # Find the corresponding Service Principal
            sp_search_url = f"{self.graph_endpoint}/servicePrincipals?$filter=appId eq '{client_id}'"
            sp_search_response = requests.get(sp_search_url, headers=headers)
            
            if not sp_search_response.ok:
                print(f"[WARN] Could not search for Service Principal: {sp_search_response.status_code}")
                return False
                
            sps = sp_search_response.json().get('value', [])
            if not sps:
                print(f"[WARN] No Service Principal found for application")
                return False
                
            sp_object_id = sps[0]['id']
            
            # Add owner to Service Principal
            url_sp_owner = f"{self.graph_endpoint}/servicePrincipals/{sp_object_id}/owners/$ref"
            body = {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"}
            resp_sp_owner = requests.post(url_sp_owner, headers=headers, json=body)
            
            if resp_sp_owner.status_code in (200, 204):
                print(f"[INFO] Added {user_email} as owner to Service Principal")
                return True
            else:
                print(f"[WARN] Failed to add owner to Service Principal: {resp_sp_owner.status_code} {resp_sp_owner.text}")
                return False
                
        except Exception as e:
            print(f"[WARN] Exception while adding Service Principal owner: {e}")
            return False

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