"""
setup_gmail_auth.py
====================
Run this ONCE, locally, on your own machine (not in GitHub Actions).
It opens a browser for you to log into Gmail and grant read access, then
prints the refresh token you'll paste into GitHub Secrets.

Prerequisites (one-time, in Google Cloud Console):
  1. Create a project at https://console.cloud.google.com
  2. Enable the "Gmail API" for that project
  3. Configure the OAuth consent screen (External, add your own email as a
     test user — you don't need to publish the app)
  4. Create an OAuth Client ID, type "Desktop app"
  5. Download the client secret JSON, save it here as client_secret.json

Then run: python setup_gmail_auth.py
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0)

print("\n--- SAVE THESE AS GITHUB SECRETS ---")
print(f"GMAIL_CLIENT_ID={creds.client_id}")
print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
print("-------------------------------------")
print("\nGo to your job-monitor repo -> Settings -> Secrets and variables -> Actions")
print("and add each of the three values above as a separate secret.")
