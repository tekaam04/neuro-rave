"""
One-time helper script to get a Spotify refresh token.

Usage:
1. Run:  python get_spotify_refresh_token.py
2. Opens the Spotify login page in your browser automatically.
3. Approve access when prompted.
4. The script automatically captures the code and updates .env.
"""

# -*- coding: utf-8 -*-

import base64
import os
import sys
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import Optional

import requests

# Import constants from src
sys.path.insert(0, str(Path(__file__).parent / "src"))
from constants import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

CLIENT_ID = SPOTIFY_CLIENT_ID
CLIENT_SECRET = SPOTIFY_CLIENT_SECRET
REDIRECT_URI = "http://127.0.0.1:8080/callback"

# Scopes: playback control + list playlists (for /spotify/playlists/suggestions).
SCOPES = [
    "user-modify-playback-state",
    "user-read-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
]


def build_auth_url():
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
    }
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)


def exchange_code_for_tokens(code):
    token_url = "https://accounts.spotify.com/api/token"
    auth_header = base64.b64encode(
        f"{CLIENT_ID}:{CLIENT_SECRET}".encode("utf-8")
    ).decode("utf-8")

    resp = requests.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _prepare_dotenv_path(env_path: Path) -> None:
    """Ensure env_path can be opened as a file.

    Docker bind-mount ``./.env:/app/.env`` creates an empty *directory* on the host
    when `.env` is missing; remove that so we can write a real file.
    """
    if not env_path.exists():
        return
    if env_path.is_file():
        return
    if env_path.is_dir():
        contents = list(env_path.iterdir())
        if contents:
            raise RuntimeError(
                f"{env_path} is a non-empty directory; move or delete its contents, then:\n"
                f"  rm -rf {env_path}"
            )
        env_path.rmdir()


def update_env_file(refresh_token: str) -> None:
    """Update or create .env file with refresh token (repo root, next to this script)."""
    env_path = Path(__file__).resolve().parent / ".env"
    _prepare_dotenv_path(env_path)

    existing_vars: dict[str, str] = {}
    if env_path.is_file():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        existing_vars[key.strip()] = value.strip()

    existing_vars["SPOTIFY_REFRESH_TOKEN"] = refresh_token

    with open(env_path, "w", encoding="utf-8") as f:
        for key, value in existing_vars.items():
            f.write(f"{key}={value}\n")

    print(f"\n✓ Wrote SPOTIFY_REFRESH_TOKEN to .env")


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""
    
    auth_code: Optional[str] = None
    error_msg: Optional[str] = None
    
    def do_GET(self):
        """Handle GET request from Spotify callback."""
        # Parse the callback URL
        if not self.path.startswith("/callback"):
            self.send_response(404)
            self.end_headers()
            return
        
        # Extract query parameters
        parsed_url = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        # Check for error
        if "error" in query_params:
            CallbackHandler.error_msg = query_params["error"][0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            error_msg = CallbackHandler.error_msg
            self.wfile.write(
                f"<html><body><h1>Error</h1><p>{error_msg}</p></body></html>".encode('utf-8')
            )
            return
        
        # Get the authorization code
        if "code" in query_params:
            CallbackHandler.auth_code = query_params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                "<html><body><h1>✓ Success!</h1><p>Authorization code received. You can close this window.</p></body></html>".encode('utf-8')
            )
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>No code received</h1></body></html>")
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def main():
    # Parse redirect URI to get host and port
    parsed_uri = urllib.parse.urlparse(REDIRECT_URI)
    host = parsed_uri.hostname or "127.0.0.1"
    port = parsed_uri.port or 8080
    
    print("Starting local server for OAuth callback...")
    
    # Start callback server in background thread
    server = HTTPServer((host, port), CallbackHandler)
    server_thread = Thread(daemon=True, target=server.serve_forever)
    server_thread.start()
    
    # Build and open auth URL
    auth_url = build_auth_url()
    print(f"\n✓ Opening Spotify login in your browser...")
    print(f"  {auth_url}\n")
    
    # Try to open browser automatically
    try:
        webbrowser.open(auth_url)
    except Exception as e:
        print(f"Could not open browser automatically. Open this URL manually:")
        print(auth_url)
    
    print("Waiting for authorization...")
    
    # Wait for callback (timeout after 5 minutes)
    import time
    timeout = time.time() + 300
    while CallbackHandler.auth_code is None and CallbackHandler.error_msg is None:
        if time.time() > timeout:
            print("❌ Timeout waiting for authorization.")
            server.shutdown()
            return
        time.sleep(0.5)
    
    # Shutdown server
    server.shutdown()
    
    # Handle errors
    if CallbackHandler.error_msg:
        print(f"❌ Authorization error: {CallbackHandler.error_msg}")
        return
    
    code = CallbackHandler.auth_code
    print(f"✓ Authorization code received!")
    
    # Exchange code for tokens
    print("Exchanging code for refresh token...")
    try:
        data = exchange_code_for_tokens(code)
    except Exception as e:
        print(f"❌ Error exchanging code: {e}")
        return
    
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print("❌ No refresh token in response")
        print(data)
        return
    
    # Update .env file
    update_env_file(refresh_token)
    
    print("\n✓ Setup complete! You can now run main.py or the Docker pipeline.")


if __name__ == "__main__":
    main()

