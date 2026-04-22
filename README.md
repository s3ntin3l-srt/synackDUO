# Synack DUO Automation Guide

Automate Synack DUO Push requests without needing a physical device and save the required token for further automation processes.

## Prerequisites
- Python3
- Libraries: pycryptodome, requests, beautifulsoup4

Install the necessary libraries:
```bash
pip install -r requirements.txt
```

## Setting up ruo
1. Execute `main.py`.
2. Enter the code from the QR code (use an alternative QR code scanner) or via the link provided in the email (accessible on a desktop).
  The proceess in screenshots is similar to this:
  
<img width="272" alt="Screenshot 2024-05-06 at 05 48 56" src="https://github.com/dinosn/synackDUO/assets/3851678/4e9435fa-8b9e-4800-9f68-75ffacf6e898"> ,
<img width="300" alt="Screenshot 2024-05-06 at 05 50 15" src="https://github.com/dinosn/synackDUO/assets/3851678/1f566215-f124-4c43-b701-8b5dc66613bb"> , 
<img width="260" alt="Screenshot 2024-05-06 at 05 50 47" src="https://github.com/dinosn/synackDUO/assets/3851678/27333bad-c874-47b2-ba33-78a50d2e1137"> , 
<img width="260" alt="Screenshot 2024-05-06 at 05 51 03" src="https://github.com/dinosn/synackDUO/assets/3851678/313ac430-3257-4bce-9075-2c191fc207c9"> , 
<img width="274" alt="Screenshot 2024-05-06 at 05 51 12" src="https://github.com/dinosn/synackDUO/assets/3851678/5146f0c3-b918-4cba-adcc-7a2ec04f54ae"> .

You need this token which must be passed to main.py, do `not` press the Activate DUO Mobile, you only need the token.
<img width="1392" alt="Screenshot 2025-03-17 at 19 27 39" src="https://github.com/user-attachments/assets/a46a89b1-4c87-4080-9c35-040eb339b527" />


## Using synconnect (Selenium-based token generation)
### Preparation
1. Complete the ruo setup.
2. In `synconnect.py`, update your credentials at lines 12 and 13.
3. To run in headless mode (without opening a browser window), set `options.headless = True` on line 37.
4. (Optional) Customize Token Storage Location
   - To save the token in a different location, modify the `file_path` on line 16.
   - By default, the token is stored in `/tmp/synacktoken`.

### Running the Script
Execute the script using Python:
```bash
python3 synconnect.py
```

## Using synconnect_cli (Requests-based token generation)
### Configuring device pkeys

The two pkey constants in the script — `PRIMARY_PKEY` and `FALLBACK_PKEY` — need to be set to the Duo device keys enrolled on your account. These values are **account-specific** and will not match the placeholders.

### How to find your pkeys

Duo exposes the full list of enrolled push devices at:

```
GET https://api-<subdomain>.duosecurity.com/prompt/<AKEY>/pre_authn/evaluation?authkey=<AUTHKEY>&browser_features=<...>&local_trust_choice=undecided
```

This call is made automatically during a normal browser login. To capture it:

1. Start an intercepting proxy (Burp, mitmproxy, etc.) with your browser routed through it.
2. Log in to Synack normally — Duo will show the push prompt.
3. In your proxy's history, find the request to `/pre_authn/evaluation`.
4. Inspect the JSON response body. Look for `response.available_unified_auth_factors.factors` — each push-capable device appears as:

   ```json
   {
     "factor_type": "push",
     "device_info": {
       "pkey": "DPxxxxxxxxxxxxxxxxxx",
       "name": "Android"
     }
   }
   ```

Copy the `pkey` values for your devices.

### Which pkey goes where

- **`PRIMARY_PKEY`** — set this to your **auto-approver device** (the one `main.py` taps "Approve" on automatically). This is the device the script will push to first.
- **`FALLBACK_PKEY`** — set this to your **personal device** (your regular phone). If the primary push doesn't get approved within the timeout, the script falls back to this one and you can approve manually.

If you only have one push device enrolled, leave `FALLBACK_PKEY` set to the same value as primary or to any string — the fallback simply won't trigger.

### Running the Script
Execute using Python:
```bash
python3 synconnect_cli.py
```

## Known Issue and Solution
For the automation to work correctly, the device set up for this script must be the primary device. If it's not, request to make it primary or do so manually by removing previous devices and re-adding them later.

Alternatively, use `synconnect_cli.py` with the correct configuration to circumvent this issue.

### Mission Bot
Execute using Python:
```bash
python3 mission.py
```
If you want to use it standalone as a script and provide your own token, comment out the following lines.  Token is always read from /tmp/synacktoken.
```
 71                   subprocess.run(["python3", "synconnect_cli.py"])
 72                   token = read_token_from_file(token_file_path)
```

### Mission Bot [mission_bot_token_on_cli.py]
Usage:
```
python3 mission_bot_token_on_cli.py 'TOKEN'
```
Your token can be found on your browser when you are logged in in the platform under the name `shared-session-com.synack.accessToken`
