"""Refresh the long-lived Instagram token and store it back in the IG_TOKEN repo secret.

Env: IG_TOKEN, GH_TOKEN (a PAT allowed to write repo secrets), GITHUB_REPOSITORY
"""

import os
import subprocess
import sys

import requests

token = os.environ['IG_TOKEN'].strip()
resp = requests.get('https://graph.instagram.com/refresh_access_token',
                    params={'grant_type': 'ig_refresh_token', 'access_token': token}, timeout=60)
if not resp.ok:
    print(f'ERROR refreshing token: HTTP {resp.status_code}\n{resp.text.replace(token, "***")}', file=sys.stderr)
    sys.exit(1)

data = resp.json()
new = data['access_token']
print(f'::add-mask::{new}')
# Piped over stdin so the token never appears in argv or the log.
subprocess.run(['gh', 'secret', 'set', 'IG_TOKEN', '--repo', os.environ['GITHUB_REPOSITORY']],
               input=new, text=True, check=True)
print(f"IG_TOKEN refreshed, valid for {data.get('expires_in', 0) // 86400} days")
