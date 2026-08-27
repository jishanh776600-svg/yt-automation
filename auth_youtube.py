import sys
import webbrowser
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube"
]

PROJECT_ROOT = Path(__file__).resolve().parent
CLIENT_SECRETS_FILE = PROJECT_ROOT / "client_secret.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"


def main():
    print("[+] Starting YouTube Channel Authentication...", flush=True)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE),
        scopes=SCOPES
    )
    print("\n>>> Waiting for your browser login... <<<\n", flush=True)
    credentials = flow.run_local_server(
        host="localhost",
        port=8080,
        authorization_prompt_message="Please visit this URL to authorize: {url}",
        success_message="Authentication successful! You can close this tab now.",
        open_browser=True
    )
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())
    print("\n[SUCCESS] token.json saved! Your YouTube channel is fully authorized.\n", flush=True)


if __name__ == "__main__":
    main()
