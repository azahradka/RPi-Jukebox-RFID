#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spotify Authentication Setup Tool

One-time setup script to authenticate Phoniebox with Spotify.
This script initiates the OAuth 2.0 flow and saves the encrypted credentials.

Usage:
    cd ~/RPi-Jukebox-RFID
    source .venv/bin/activate
    python tools/spotify_auth_setup.py

Prerequisites:
1. Spotify Premium account
2. Spotify Developer App created at https://developer.spotify.com/dashboard
3. Client ID and Client Secret from Spotify Developer Dashboard
4. Redirect URI configured in Spotify app: http://127.0.0.1:8888/callback
5. Configuration in jukebox.yaml with client_id and client_secret

The script will:
1. Load credentials from jukebox.yaml
2. Start a temporary local web server on port 8888
3. Open browser to Spotify authorization page
4. Capture the authorization code from redirect
5. Exchange code for access token
6. Save encrypted credentials
7. Test API connection

After successful authentication, the Spotify player plugin will automatically
refresh tokens as needed.
"""

import sys
import logging
from pathlib import Path
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Import SpotifyAuthManager directly to avoid triggering __init__.py plugin registration
import importlib.util  # noqa: E402
_auth_spec = importlib.util.spec_from_file_location(
    'spotify_auth',
    str(PROJECT_ROOT / 'src' / 'jukebox' / 'components' / 'playerspotify' / 'spotify_auth.py')
)
_auth_module = importlib.util.module_from_spec(_auth_spec)
_auth_spec.loader.exec_module(_auth_module)
SpotifyAuthManager = _auth_module.SpotifyAuthManager

import spotipy  # noqa: E402

try:
    from ruamel.yaml import YAML

    def _load_yaml(path):
        return YAML().load(open(path))
except ImportError:
    import yaml

    def _load_yaml(path):  # noqa: F811
        with open(path) as f:
            return yaml.safe_load(f)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SpotifyAuthSetup')


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth callback"""

    auth_code = None
    auth_error = None

    def log_message(self, format, *args):
        """Suppress default logging"""
        pass

    def do_GET(self):
        """Handle GET request from OAuth redirect"""
        # Parse URL
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if 'code' in params:
            # Success - got authorization code
            CallbackHandler.auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <head><title>Phoniebox - Spotify Auth</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: #1DB954;">Authentication Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                    <p>Phoniebox is now connected to your Spotify account.</p>
                </body>
                </html>
            """)
        elif 'error' in params:
            # Error during authorization
            CallbackHandler.auth_error = params['error'][0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error_msg = params['error'][0]
            html = f"""
                <html>
                <head><title>Phoniebox - Spotify Auth Error</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: #E74C3C;">Authentication Failed</h1>
                    <p>Error: {error_msg}</p>
                    <p>Please try again or check your Spotify app configuration.</p>
                </body>
                </html>
            """
            self.wfile.write(html.encode())
        else:
            # Unknown request
            self.send_response(404)
            self.end_headers()


def start_callback_server(port=8888, timeout=300):
    """
    Start temporary HTTP server to capture OAuth callback

    Args:
        port: Port to listen on (must match redirect_uri)
        timeout: Max seconds to wait for callback

    Returns:
        Authorization code or None if timeout/error
    """
    server = HTTPServer(('', port), CallbackHandler)
    server.timeout = 1  # 1 second timeout for accept

    logger.info(f"Started callback server on port {port}")
    logger.info(f"Waiting for authorization (timeout: {timeout}s)...")

    # Run server in loop until we get auth code or timeout
    for _ in range(timeout):
        server.handle_request()
        if CallbackHandler.auth_code or CallbackHandler.auth_error:
            break

    server.server_close()

    if CallbackHandler.auth_error:
        logger.error(f"Authorization error: {CallbackHandler.auth_error}")
        return None

    return CallbackHandler.auth_code


def main():
    """Main setup flow"""
    print("\n" + "=" * 60)
    print("Phoniebox Spotify Authentication Setup")
    print("=" * 60 + "\n")  # noqa: W503

    # Load jukebox configuration directly from YAML
    # (we don't use jukebox.cfghandler because it requires the daemon context)
    config_path = PROJECT_ROOT / 'shared' / 'settings' / 'jukebox.yaml'
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        logger.error("Make sure you're running from the RPi-Jukebox-RFID directory")
        logger.error("Usage: cd ~/RPi-Jukebox-RFID && python tools/spotify_auth_setup.py")
        sys.exit(1)

    try:
        logger.info(f"Loading configuration from {config_path}...")
        cfg = _load_yaml(config_path)
    except Exception as e:
        logger.error(f"Failed to load jukebox configuration: {e}")
        sys.exit(1)

    # Get Spotify credentials from config
    spotify_cfg = cfg.get('playerspotify', {})
    client_id = spotify_cfg.get('client_id', '')
    client_secret = spotify_cfg.get('client_secret', '')
    redirect_uri = spotify_cfg.get('redirect_uri',
                                   'http://127.0.0.1:8888/callback')
    credential_file = spotify_cfg.get('credential_file',
                                      '../../shared/settings/spotify_credentials.json')

    # Resolve relative credential_file path (relative to src/jukebox/components/playerspotify/)
    if credential_file.startswith('../../'):
        credential_file = str(PROJECT_ROOT / credential_file.replace('../../', ''))

    # Validate configuration
    if not client_id or not client_secret:
        logger.error("Spotify credentials not configured!")
        logger.error("Please add client_id and client_secret to shared/settings/jukebox.yaml")
        logger.error("\nSteps:")
        logger.error("1. Go to https://developer.spotify.com/dashboard")
        logger.error("2. Create or select your app")
        logger.error("3. Copy Client ID and Client Secret")
        logger.error("4. Add to playerspotify section in jukebox.yaml:")
        logger.error("   client_id: 'your_client_id'")
        logger.error("   client_secret: 'your_client_secret'")
        logger.error(f"5. Ensure redirect URI is set to: {redirect_uri}")
        sys.exit(1)

    logger.info(f"Client ID: {client_id[:10]}...")
    logger.info(f"Redirect URI: {redirect_uri}")

    # Initialize auth manager
    try:
        auth_manager = SpotifyAuthManager(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            credential_file=credential_file
        )
    except Exception as e:
        logger.error(f"Failed to initialize auth manager: {e}")
        sys.exit(1)

    # Get authorization URL
    auth_url = auth_manager.get_auth_url()
    logger.info("\nOpening browser for Spotify authorization...")
    logger.info(f"If browser doesn't open, visit this URL:\n{auth_url}\n")

    # Open browser
    try:
        webbrowser.open(auth_url)
    except Exception as e:
        logger.warning(f"Failed to open browser: {e}")
        logger.info("Please open the URL manually")

    # Extract port from redirect_uri
    parsed_uri = urlparse(redirect_uri)
    port = parsed_uri.port or 8888

    # Start callback server
    auth_code = start_callback_server(port=port, timeout=300)

    if not auth_code:
        logger.error("Failed to receive authorization code")
        logger.error("Please check:")
        logger.error(f"1. Redirect URI in Spotify app matches: {redirect_uri}")
        logger.error(f"2. Port {port} is not blocked by firewall")
        logger.error("3. You granted permissions in the browser")
        sys.exit(1)

    logger.info("Authorization code received!")

    # Exchange code for token
    try:
        logger.info("Exchanging authorization code for access token...")
        token_info = auth_manager.authenticate(auth_code)
        logger.info("Access token obtained successfully!")
    except Exception as e:
        logger.error(f"Failed to obtain access token: {e}")
        sys.exit(1)

    # Test API connection
    try:
        logger.info("Testing Spotify API connection...")
        sp = spotipy.Spotify(auth=token_info['access_token'])
        user = sp.current_user()
        logger.info("Successfully connected to Spotify!")
        logger.info(f"User: {user['display_name']} ({user['id']})")

        # Check for Premium account
        if user.get('product') != 'premium':
            logger.warning("\nWARNING: Your account is not Spotify Premium!")
            logger.warning("Playback control requires Spotify Premium subscription.")
            logger.warning("Some features may not work without Premium.")
    except Exception as e:
        logger.error(f"API connection test failed: {e}")
        logger.error("Authentication was successful but API test failed")
        logger.error("This might still work - try using the plugin")

    print("\n" + "=" * 60)  # noqa: W503
    print("Setup Complete!")
    print("=" * 60)  # noqa: W503
    print("\nNext steps:")
    print("1. Start/restart jukebox: systemctl --user restart jukebox-daemon")
    print("2. Check logs: journalctl --user -u jukebox-daemon -f")
    print("3. Test with RPC: ./tools/run_rpc_tool.sh")
    print("   > playerspotify.ctrl.play_content spotify:track:11dFghVXANMlKmJXsNCbNl")
    print("\nAdd Spotify URIs to cards.yaml to trigger with RFID cards.")
    print(f"\nCredentials saved to: {credential_file}")
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user")
        sys.exit(0)
    except Exception:
        logger.exception("Unexpected error during setup")
        sys.exit(1)
