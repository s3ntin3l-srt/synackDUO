import subprocess
import sys
import requests
from bs4 import BeautifulSoup
import time

# Constants
EMAIL = ""
PASSWORD = ""
DUO_POLL_INTERVAL = 2  # seconds
MAX_RETRIES = 3
DEVICE_KEY = ""
file_path = '/tmp/synacktoken'


def synack():
    def is_json(response):
        try:
            response.json()
            return True
        except ValueError:
            return False

    # Function to exit on error with a message
    def exit_on_error(message):
        print(message)
        sys.exit(1)

    # Initialize a session with a cookie jar
    session = requests.Session()
    session.cookies = requests.cookies.RequestsCookieJar()

    # Custom headers
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br"
    }

    # Step 1: GET request to login.synack.com to fetch CSRF token
    try:
        response = session.get('https://login.synack.com', headers=custom_headers)
        if response.status_code != 200:
            exit_on_error("Failed to fetch CSRF token")
        soup = BeautifulSoup(response.text, 'html.parser')
        csrf_token = soup.find('meta', {'name': 'csrf-token'})['content']
    except Exception as e:
        exit_on_error(f"Error during fetching CSRF token: {e}")

    # Step 2: POST request to /api/authenticate with credentials
    for attempt in range(MAX_RETRIES):
        try:
            login_url = 'https://login.synack.com/api/authenticate'
            login_data = {"email": EMAIL, "password": PASSWORD}
            headers = {'X-Csrf-Token': csrf_token}
            response = session.post(login_url, json=login_data, headers=headers)
            
            if response.status_code == 200 and is_json(response):
                response_data = response.json()
                duo_auth_url = response_data.get('duo_auth_url')
                if duo_auth_url:
                    print("[!] Login successful on attempt {}".format(attempt + 1))
                    break  # Successful login, break out of the loop
                else:
                    exit_on_error("Duo Auth URL missing in response")
            else:
                print(f"Login attempt {attempt + 1} failed, status code: {response.status_code}, retrying...")
                if attempt == MAX_RETRIES - 1:
                    exit_on_error("Login failed after maximum retries")

        except Exception as e:
            print(f"Login attempt {attempt + 1} failed with error: {e}")
            if attempt == MAX_RETRIES - 1:
                exit_on_error("Error during login after maximum retries: {e}")



    # Step 3: Navigate Duo OAuth entry — follow all redirects to the prompt page
    try:
        response = session.get(duo_auth_url, headers=custom_headers)
        if response.status_code != 200:
            exit_on_error("Failed to reach Duo prompt page")
        session.cookies.update(response.cookies)
        akey = response.url.split('/prompt/')[1].split('?')[0]
        authkey = response.url.split('authkey=')[1].split('&')[0]
        req_trace_group = response.url.split('req_trace_group=')[1].split('&')[0] if 'req_trace_group' in response.url else ''
    except Exception as e:
        exit_on_error(f"Error during Duo OAuth entry: {e}")

    # Step 4: GET auth payload
    try:
        browser_features = '{"touch_supported":false,"platform_authenticator_status":"unavailable","webauthn_supported":true,"screen_resolution_height":1080,"screen_resolution_width":1920,"screen_color_depth":24,"is_uvpa_available":false,"client_capabilities_uvpa":false}'
        api_headers = {**custom_headers, 'X-Duo-Req-Trace-Group': req_trace_group}
        payload_url = f'https://api-64d8e0cf.duosecurity.com/prompt/{akey}/auth/payload?authkey={authkey}&browser_features={requests.utils.quote(browser_features)}'
        response = session.get(payload_url, headers=api_headers)
        if response.status_code != 200:
            exit_on_error("Failed to GET auth payload")
        session.cookies.update(response.cookies)
    except Exception as e:
        exit_on_error(f"Error during auth payload: {e}")

    # Step 5: Pre-auth initialization
    try:
        init_url = f'https://api-64d8e0cf.duosecurity.com/prompt/{akey}/pre_authn/initialization?authkey={authkey}&is_ipad=false'
        response = session.get(init_url, headers=api_headers)
        if response.status_code != 200:
            exit_on_error("Failed to GET pre-auth initialization")
        session.cookies.update(response.cookies)
    except Exception as e:
        exit_on_error(f"Error during pre-auth initialization: {e}")

    # Step 6: Pre-auth evaluation — get available push devices
    try:
        eval_url = f'https://api-64d8e0cf.duosecurity.com/prompt/{akey}/pre_authn/evaluation?authkey={authkey}&browser_features={requests.utils.quote(browser_features)}&local_trust_choice=undecided'
        response = session.get(eval_url, headers=api_headers)
        if response.status_code != 200:
            exit_on_error("Failed to GET pre-auth evaluation")
        session.cookies.update(response.cookies)
        factors = response.json()['response']['available_unified_auth_factors']['factors']
        push_factors = [f for f in factors if f['factor_type'] == 'push']
        if not push_factors:
            exit_on_error("No push factors available")
        pkey = DEVICE_KEY if DEVICE_KEY else push_factors[0]['device_info']['pkey']
    except Exception as e:
        exit_on_error(f"Error during pre-auth evaluation: {e}")
    # Step 7: Send Duo Push notification
    try:
        push_url = f'https://api-64d8e0cf.duosecurity.com/prompt/{akey}/auth/factors/push/auth'
        push_response = session.post(push_url, json={'authkey': authkey, 'pkey': pkey}, headers=api_headers)
        if push_response.status_code != 200 or not is_json(push_response):
            exit_on_error("Failed to send Duo Push")
        push_txid = push_response.json()['response']['push_txid']
        subprocess.run(["python3", "main.py"], check=True)
    except Exception as e:
        exit_on_error(f"Error sending Duo Push: {e}")

    # Step 8: Poll for Duo Push approval
    try:
        status_url = f'https://api-64d8e0cf.duosecurity.com/prompt/{akey}/auth/factors/push/status?authkey={authkey}&push_txid={push_txid}&saw_good_news=false'
        while True:
            status_response = session.get(status_url, headers=api_headers)
            if status_response.status_code != 200 or not is_json(status_response):
                exit_on_error("Failed to poll Duo Push status")
            result = status_response.json()['response']['result']['result']
            if result == 'SUCCESS':
                session.cookies.update(status_response.cookies)
                break
            elif result not in ('STATUS',):
                exit_on_error(f"Duo Push failed with result: {result}")
            time.sleep(DUO_POLL_INTERVAL)
    except Exception as e:
        exit_on_error(f"Error polling Duo Push status: {e}")


    # Step 9: Remember me + finalize auth to get OIDC exit URL
    try:
        session.post(f'https://api-64d8e0cf.duosecurity.com/prompt/{akey}/auth/remember_me',
                     json={'authkey': authkey}, headers=api_headers)
        finalize_response = session.get(f'https://api-64d8e0cf.duosecurity.com/prompt/{akey}/auth/finalize_auth?authkey={authkey}',
                                        headers=api_headers)
        if finalize_response.status_code != 200 or not is_json(finalize_response):
            exit_on_error("Failed to finalize Duo auth")
        oidc_exit_url = finalize_response.json()['response']['url']
    except Exception as e:
        exit_on_error(f"Error during finalize auth: {e}")


    # Step 10: Follow OIDC exit redirect chain to Synack grant token
    try:
        final_response = session.get(oidc_exit_url, headers=custom_headers)
        if final_response.status_code != 200:
            exit_on_error("Failed during final redirect to Synack")
        grant_token = final_response.url.split('grant_token=')[1].split('&')[0]
    except Exception as e:
        exit_on_error(f"Error during final redirect: {e}")

    # Step 11: GET request to /token?grant_token= to receive access_token
    headers['X-Requested-With'] = 'XMLHttpRequest'
    response = requests.get(f'https://platform.synack.com/token?grant_token={grant_token}', headers=headers)
    #print("Text:", response.text)
    access_token = response.json().get('access_token') if is_json(response) else None
    return access_token

def write_token_to_file(token, file_path):
    try:
        with open(file_path, 'w') as file:
            file.write(token)
    except Exception as e:
        print(f"Error writing to file: {e}")


auth = synack()

print("Access-Token:", auth)

write_token_to_file(auth, file_path)