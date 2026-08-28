import sys
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/drive"
]

PROJECT_ROOT = Path(__file__).resolve().parent
CLIENT_SECRETS_FILE = PROJECT_ROOT / "client_secret.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code = None
    error = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family: sans-serif; text-align: center; padding: 60px;'>"
                b"<h1 style='color: #2e7d32;'>&#10004; Authentication Successful!</h1>"
                b"<p style='font-size: 18px;'>Google Drive &amp; YouTube permissions have been granted.</p>"
                b"<p style='color: #666;'>You can close this browser tab now and return to Antigravity.</p>"
                b"</body></html>"
            )
        elif "error" in params:
            OAuthCallbackHandler.error = params["error"][0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Authentication error: {OAuthCallbackHandler.error}".encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default HTTP server noise


def main():
    print("[+] Starting Unified YouTube & Google Drive Authentication...", flush=True)
    port = 8080
    redirect_uri = f"http://localhost:{port}/"

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )

    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true"
    )

    print("\n=======================================================", flush=True)
    print("PLEASE COMPLETE AUTHORIZATION IN YOUR BROWSER:", flush=True)
    print(auth_url, flush=True)
    print("=======================================================\n", flush=True)

    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.timeout = 300  # 5 minutes timeout

    # Open browser automatically
    webbrowser.open(auth_url)

    print("[*] Waiting for OAuth callback on http://localhost:8080/ ...", flush=True)
    while OAuthCallbackHandler.auth_code is None and OAuthCallbackHandler.error is None:
        server.handle_request()

    server.server_close()

    if OAuthCallbackHandler.error:
        print(f"\n[ERROR] Authorization denied or failed: {OAuthCallbackHandler.error}", flush=True)
        sys.exit(1)

    code = OAuthCallbackHandler.auth_code
    print("[+] Authorization code received from Google. Exchanging for permanent tokens...", flush=True)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())

    print("\n[SUCCESS] token.json saved successfully!", flush=True)
    print(f"Granted Scopes ({len(credentials.scopes)}): {credentials.scopes}", flush=True)
    print(f"Refreshable: {bool(credentials.refresh_token)}\n", flush=True)


if __name__ == "__main__":
    main()
