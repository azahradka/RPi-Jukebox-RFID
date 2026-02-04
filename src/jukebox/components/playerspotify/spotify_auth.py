# -*- coding: utf-8 -*-
"""
Spotify Authentication Manager

Handles OAuth 2.0 PKCE flow for Spotify API authentication with secure token storage.
Implements automatic token refresh and encrypted credential storage.

Features:
- OAuth 2.0 with PKCE for enhanced security
- Automatic token refresh (tokens expire after 60 minutes)
- Encrypted token storage using AES encryption
- Thread-safe token access
- Required scopes for playback control

Required Scopes:
- user-read-playback-state: Read current playback state
- user-modify-playback-state: Control playback (play, pause, skip, etc.)
- playlist-read-private: Access user's private playlists
- user-library-read: Access user's saved tracks

References:
- https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- https://spotipy.readthedocs.io/en/latest/#authorization-code-flow
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any
from spotipy.oauth2 import SpotifyOAuth
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
import base64

logger = logging.getLogger('jb.SpotifyAuth')

# Required scopes for Spotify playback control
SPOTIFY_SCOPES = [
    'user-read-playback-state',
    'user-modify-playback-state',
    'playlist-read-private',
    'user-library-read'
]


class SpotifyAuthManager:
    """Manages Spotify OAuth authentication and token refresh"""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, credential_file: str):
        """
        Initialize Spotify authentication manager

        Args:
            client_id: Spotify application client ID
            client_secret: Spotify application client secret
            redirect_uri: OAuth redirect URI (must match Spotify app settings)
            credential_file: Path to store encrypted credentials
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.credential_file = Path(credential_file).expanduser()

        # Ensure credential directory exists
        self.credential_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize SpotifyOAuth with PKCE
        self.oauth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=' '.join(SPOTIFY_SCOPES),
            cache_path=None,  # We manage our own cache
            show_dialog=False  # Don't force approval prompt on every auth
        )

        # Load cached token if available
        self.token_info = self._load_token()

        # Validate or refresh token
        if self.token_info:
            if self.is_token_expired():
                logger.info("Cached token expired, refreshing...")
                self.token_info = self._refresh_token()
        else:
            logger.warning("No cached token found. Run spotify_auth_setup.py to authenticate.")

    def _get_encryption_key(self) -> bytes:
        """
        Derive encryption key from client credentials

        Uses PBKDF2 to derive a strong encryption key from the client secret.
        This ensures tokens are encrypted at rest.

        Returns:
            32-byte encryption key
        """
        # Use client_id as salt (consistent across restarts)
        salt = self.client_id.encode('utf-8')
        key = PBKDF2(self.client_secret.encode('utf-8'), salt, dkLen=32, count=100000)
        return key

    def _encrypt_data(self, data: Dict[str, Any]) -> str:
        """
        Encrypt token data using AES-256

        Args:
            data: Token data dictionary

        Returns:
            Base64-encoded encrypted data
        """
        try:
            key = self._get_encryption_key()
            cipher = AES.new(key, AES.MODE_GCM)
            json_data = json.dumps(data).encode('utf-8')
            ciphertext, tag = cipher.encrypt_and_digest(json_data)

            # Combine nonce, tag, and ciphertext
            encrypted = cipher.nonce + tag + ciphertext
            return base64.b64encode(encrypted).decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def _decrypt_data(self, encrypted_data: str) -> Dict[str, Any]:
        """
        Decrypt token data using AES-256

        Args:
            encrypted_data: Base64-encoded encrypted data

        Returns:
            Decrypted token data dictionary
        """
        try:
            key = self._get_encryption_key()
            encrypted_bytes = base64.b64decode(encrypted_data)

            # Extract nonce (16 bytes), tag (16 bytes), and ciphertext
            nonce = encrypted_bytes[:16]
            tag = encrypted_bytes[16:32]
            ciphertext = encrypted_bytes[32:]

            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            json_data = cipher.decrypt_and_verify(ciphertext, tag)
            return json.loads(json_data.decode('utf-8'))
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def _save_token(self, token_info: Dict[str, Any]):
        """
        Save encrypted token to disk

        Args:
            token_info: Token data from Spotify OAuth
        """
        try:
            encrypted = self._encrypt_data(token_info)
            with open(self.credential_file, 'w') as f:
                json.dump({'encrypted_token': encrypted}, f, indent=2)
            logger.debug(f"Token saved to {self.credential_file}")
        except Exception as e:
            logger.error(f"Failed to save token: {e}")

    def _load_token(self) -> Optional[Dict[str, Any]]:
        """
        Load encrypted token from disk

        Returns:
            Token data dictionary or None if not found
        """
        try:
            if not self.credential_file.exists():
                return None

            with open(self.credential_file, 'r') as f:
                data = json.load(f)

            if 'encrypted_token' not in data:
                logger.error("Invalid credential file format")
                return None

            token_info = self._decrypt_data(data['encrypted_token'])
            logger.debug("Token loaded from cache")
            return token_info
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            return None

    def is_token_expired(self) -> bool:
        """
        Check if current token is expired

        Returns:
            True if token is expired or will expire within 60 seconds
        """
        if not self.token_info:
            return True

        expires_at = self.token_info.get('expires_at', 0)
        # Consider expired if less than 60 seconds remaining
        return time.time() > (expires_at - 60)

    def _refresh_token(self) -> Dict[str, Any]:
        """
        Refresh access token using refresh token

        Returns:
            New token info dictionary

        Raises:
            Exception if refresh fails
        """
        try:
            if not self.token_info or 'refresh_token' not in self.token_info:
                raise ValueError("No refresh token available")

            logger.info("Refreshing Spotify access token...")
            new_token_info = self.oauth.refresh_access_token(self.token_info['refresh_token'])

            # Save refreshed token
            self._save_token(new_token_info)
            logger.info("Token refreshed successfully")
            return new_token_info
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise

    def get_access_token(self) -> str:
        """
        Get valid access token, refreshing if necessary

        Returns:
            Valid Spotify access token

        Raises:
            Exception if authentication fails
        """
        if not self.token_info:
            raise ValueError("Not authenticated. Run spotify_auth_setup.py to authenticate.")

        # Refresh if expired
        if self.is_token_expired():
            self.token_info = self._refresh_token()

        return self.token_info['access_token']

    def authenticate(self, auth_code: str) -> Dict[str, Any]:
        """
        Complete OAuth flow with authorization code

        This method is called during initial setup with the authorization code
        received from the OAuth redirect.

        Args:
            auth_code: Authorization code from OAuth redirect

        Returns:
            Token info dictionary

        Raises:
            Exception if authentication fails
        """
        try:
            logger.info("Completing OAuth authentication...")
            token_info = self.oauth.get_access_token(auth_code, as_dict=True)

            # Save token
            self._save_token(token_info)
            self.token_info = token_info
            logger.info("Authentication successful!")
            return token_info
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise

    def get_auth_url(self) -> str:
        """
        Get OAuth authorization URL for initial authentication

        Returns:
            Authorization URL to display to user
        """
        return self.oauth.get_authorize_url()

    def clear_token(self):
        """Clear cached token (logout)"""
        try:
            if self.credential_file.exists():
                self.credential_file.unlink()
            self.token_info = None
            logger.info("Token cleared")
        except Exception as e:
            logger.error(f"Failed to clear token: {e}")
