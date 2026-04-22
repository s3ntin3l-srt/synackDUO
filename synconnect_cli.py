import base64
import json
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse
import requests
from bs4 import BeautifulSoup

# Constants
EMAIL = ""
PASSWORD = ""
DUO_POLL_INTERVAL = 2  # seconds
MAX_RETRIES = 3
PRIMARY_PKEY = "DPxxxx" # Refer README for more info
FALLBACK_PKEY = "DPxxxx" # Refer README for more info
file_path = '/tmp/synacktoken'

BROWSER_FEATURES = (
    '{"touch_supported":false,"platform_authenticator_status":"unavailable",'
    '"webauthn_supported":true,"screen_resolution_height":1112,'
    '"screen_resolution_width":1710,"screen_color_depth":30,'
    '"is_uvpa_available":false,"client_capabilities_uvpa":false}'
)
CLIENT_HINTS = base64.b64encode(json.dumps({
    "brands": [{"brand": "Not-A.Brand", "version": "24"},
               {"brand": "Chromium", "version": "146"}],
    "fullVersionList": [], "mobile": False,
    "platform": "macOS", "platformVersion": "", "uaFullVersion": "",
}).encode()).decode()


def synack():
    def is_json(response):
        try:
            response.json()
            return True
        except ValueError:
            return False

    def exit_on_error(message):
        print(message)
        sys.exit(1)

    session = requests.Session()
    session.cookies = requests.cookies.RequestsCookieJar()

    custom_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/146.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://login.synack.com/",
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
    duo_auth_url = None
    for attempt in range(MAX_RETRIES):
        try:
            response = session.post(
                'https://login.synack.com/api/authenticate',
                json={"email": EMAIL, "password": PASSWORD},
                headers={'X-Csrf-Token': csrf_token},
            )
            if response.status_code == 200 and is_json(response):
                duo_auth_url = response.json().get('duo_auth_url')
                if duo_auth_url:
                    print(f"[!] Login successful on attempt {attempt + 1}")
                    break
                exit_on_error("Duo Auth URL missing in response")
            else:
                print(f"Login attempt {attempt + 1} failed, status code: "
                      f"{response.status_code}, retrying...")
                if attempt == MAX_RETRIES - 1:
                    exit_on_error("Login failed after maximum retries")
        except Exception as e:
            print(f"Login attempt {attempt + 1} failed with error: {e}")
            if attempt == MAX_RETRIES - 1:
                exit_on_error(f"Error during login after maximum retries: {e}")

    # Step 3: Follow OAuth → Duo prompt; extract akey / authkey / duo_base
    try:
        response = session.get(duo_auth_url, headers=custom_headers,
                               allow_redirects=True)
        if response.status_code != 200:
            exit_on_error(f"Duo redirect chain failed: {response.status_code}")
        parsed = urlparse(response.url)
        duo_base = f"{parsed.scheme}://{parsed.netloc}"
        if '/prompt/' not in parsed.path:
            exit_on_error(f"Unexpected Duo landing URL: {response.url}")
        akey = parsed.path.split('/prompt/')[1].split('/')[0]
        qs = parse_qs(parsed.query)
        authkey = qs.get('authkey', [None])[0]
        trace_id = qs.get('req_trace_group', [''])[0]
        if not authkey:
            exit_on_error("authkey missing from Duo prompt URL")
    except Exception as e:
        exit_on_error(f"Error during Duo redirect/extract: {e}")

    duo_headers = {
        **custom_headers,
        "Origin": duo_base,
        "Referer": f"{duo_base}/prompt/{akey}?authkey={authkey}"
                   f"&req_trace_group={trace_id}",
        "X-Duo-Req-Trace-Group": trace_id,
    }

    # Step 4: Pre-auth (payload → initialization → evaluation)
    try:
        session.get(
            f"{duo_base}/prompt/{akey}/auth/payload",
            params={'authkey': authkey, 'browser_features': BROWSER_FEATURES},
            headers=duo_headers,
        )
        session.get(
            f"{duo_base}/prompt/{akey}/pre_authn/initialization",
            params={'authkey': authkey, 'is_ipad': 'false',
                    'client_hints': CLIENT_HINTS},
            headers=duo_headers,
        )
        response = session.get(
            f"{duo_base}/prompt/{akey}/pre_authn/evaluation",
            params={'authkey': authkey, 'browser_features': BROWSER_FEATURES,
                    'local_trust_choice': 'undecided'},
            headers=duo_headers,
        )
        if not is_json(response):
            exit_on_error("pre_authn/evaluation returned non-JSON")
        enrolled = {
            f['device_info']['pkey']
            for f in response.json()['response']
                          ['available_unified_auth_factors']['factors']
            if f.get('factor_type') == 'push'
        }
    except Exception as e:
        exit_on_error(f"Error during Duo pre-auth: {e}")

    # Step 5: POST Duo push and poll, with fallback
    def trigger_push(pkey):
        r = session.post(
            f"{duo_base}/prompt/{akey}/auth/factors/push/auth",
            json={'authkey': authkey, 'pkey': pkey},
            headers={**duo_headers, "Content-Type": "application/json"},
        )
        if r.status_code != 200 or not is_json(r):
            exit_on_error(f"push/auth failed: {r.status_code} {r.text[:200]}")
        return r.json()['response']['push_txid']

    primary_pkey = (PRIMARY_PKEY if PRIMARY_PKEY in enrolled
                    else next(iter(enrolled)))
    fallback_pkey = (FALLBACK_PKEY
                     if FALLBACK_PKEY in enrolled
                     and FALLBACK_PKEY != primary_pkey
                     else None)

    def run_push_and_poll(pkey):
        txid = trigger_push(pkey)
        subprocess.run(["python3", "main.py"], check=True)
        deadline = time.time() + 60
        while time.time() < deadline:
            r = session.get(
                f"{duo_base}/prompt/{akey}/auth/factors/push/status",
                params={'authkey': authkey, 'push_txid': txid,
                        'saw_good_news': 'false'},
                headers=duo_headers,
            )
            if r.status_code != 200 or not is_json(r):
                exit_on_error(f"push/status failed: {r.status_code} {r.text[:200]}")
            result = r.json()['response']['result']['result']
            if result == 'SUCCESS':
                return True
            if result == 'STATUS':
                time.sleep(DUO_POLL_INTERVAL)
                continue
            return False
        return False

    try:
        ok = run_push_and_poll(primary_pkey)
        if not ok and fallback_pkey:
            print("Primary device did not approve. Trying fallback Android.")
            ok = run_push_and_poll(fallback_pkey)
        if not ok:
            exit_on_error("All Duo push attempts failed/timed out.")
    except Exception as e:
        exit_on_error(f"Error during push/poll: {e}")

    # Step 6: Finalize auth → follow redirects → grant_token
    try:
        response = session.get(
            f"{duo_base}/prompt/{akey}/auth/finalize_auth",
            params={'authkey': authkey}, headers=duo_headers,
        )
        if not is_json(response):
            exit_on_error("finalize_auth returned non-JSON")
        exit_url = response.json()['response']['url']

        response = session.get(exit_url, headers=custom_headers,
                               allow_redirects=True)
        if 'grant_token=' not in response.url:
            exit_on_error(f"grant_token missing from final URL: {response.url}")
        grant_token = response.url.split('grant_token=')[1].split('&')[0]
    except Exception as e:
        exit_on_error(f"Error during Duo finalize/redirect: {e}")

    # Step 7: GET request to /token?grant_token= to receive access_token
    headers = {**custom_headers, 'X-Requested-With': 'XMLHttpRequest'}
    response = requests.get(
        f'https://platform.synack.com/token?grant_token={grant_token}',
        headers=headers,
    )
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
