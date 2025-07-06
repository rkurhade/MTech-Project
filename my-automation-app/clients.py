import requests
from dotenv import load_dotenv

class AzureADClient:
    def __init__(self, config):
        self.client_id = config['client_id']
        self.client_secret = config['client_secret']
        self.tenant_id = config['tenant_id']
        self.authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.graph_endpoint = 'https://graph.microsoft.com/v1.0'

    def get_access_token(self):
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
        print(f"Error fetching access token: {response.text}")
        return None

    def search_application(self, token, app_name):
        url = f'{self.graph_endpoint}/applications?$filter=displayName eq \'{app_name}\''
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
            print(f"Error searching for service principal: {err}")
        return None

    def create_application(self, token, app_name):
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        app_data = {
            "displayName": app_name
        }

        response = requests.post(f"{self.graph_endpoint}/applications", headers=headers, json=app_data)
        if not response.ok:
            print(f"Error creating service principal: {response.text}")
            return None, None

        app = response.json()
        app_id = app.get('id')
        client_id = app.get('appId')

        secret_data = {"passwordCredential": {"displayName": f"{app_name} secret"}}
        secret_response = requests.post(f"{self.graph_endpoint}/applications/{app_id}/addPassword", headers=headers, json=secret_data)
        if secret_response.ok:
            client_secret = secret_response.json().get('secretText')
            return client_id, client_secret
        print(f"Error creating client secret: {secret_response.text}")
        return None, None

    def delete_application(self, token, client_id):
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Find the app object ID using the client_id
        search_url = f"{self.graph_endpoint}/applications?$filter=appId eq '{client_id}'"
        search_response = requests.get(search_url, headers=headers)

        if not search_response.ok:
            print(f"Error searching service principal for deletion: {search_response.text}")
            return False

        apps = search_response.json().get('value', [])
        if not apps:
            print("No service principal found to delete.")
            return False

        app_object_id = apps[0]['id']

        # Delete the application using the object ID
        delete_url = f"{self.graph_endpoint}/applications/{app_object_id}"
        delete_response = requests.delete(delete_url, headers=headers)

        if delete_response.status_code == 204:
            print("Successfully rolled back service principal.")
            return True
        else:
            print(f"Failed to delete service principal: {delete_response.text}")
            return False