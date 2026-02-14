# -*- coding: utf-8 -*-
"""Unit tests for Spotify authentication manager"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from components.playerspotify.spotify_auth import SpotifyAuthManager


@pytest.fixture
def temp_credential_file():
    """Create temporary credential file"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        yield f.name
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def auth_manager(temp_credential_file):
    """Create SpotifyAuthManager instance with test credentials"""
    return SpotifyAuthManager(
        client_id='test_client_id',
        client_secret='test_client_secret',
        redirect_uri='http://localhost:8888/callback',
        credential_file=temp_credential_file
    )


def test_initialization(auth_manager):
    """Test auth manager initialization"""
    assert auth_manager.client_id == 'test_client_id'
    assert auth_manager.client_secret == 'test_client_secret'
    assert auth_manager.redirect_uri == 'http://localhost:8888/callback'
    assert auth_manager.oauth is not None


def test_encryption_decryption(auth_manager):
    """Test data encryption and decryption"""
    test_data = {
        'access_token': 'test_token_123',
        'refresh_token': 'test_refresh_456',
        'expires_at': 1234567890
    }

    # Encrypt
    encrypted = auth_manager._encrypt_data(test_data)
    assert isinstance(encrypted, str)
    assert encrypted != str(test_data)

    # Decrypt
    decrypted = auth_manager._decrypt_data(encrypted)
    assert decrypted == test_data


def test_save_and_load_token(auth_manager, temp_credential_file):
    """Test token saving and loading"""
    token_info = {
        'access_token': 'test_access_token',
        'refresh_token': 'test_refresh_token',
        'expires_at': time.time() + 3600,
        'scope': 'user-read-playback-state',
        'token_type': 'Bearer'
    }

    # Save token
    auth_manager._save_token(token_info)

    # Verify file exists
    assert Path(temp_credential_file).exists()

    # Load token
    loaded_token = auth_manager._load_token()
    assert loaded_token is not None
    assert loaded_token['access_token'] == token_info['access_token']
    assert loaded_token['refresh_token'] == token_info['refresh_token']


def test_token_expiration_check(auth_manager):
    """Test token expiration detection"""
    # No token
    assert auth_manager.is_token_expired() is True

    # Expired token
    auth_manager.token_info = {
        'expires_at': time.time() - 100
    }
    assert auth_manager.is_token_expired() is True

    # Valid token (expires in 2 hours)
    auth_manager.token_info = {
        'expires_at': time.time() + 7200
    }
    assert auth_manager.is_token_expired() is False

    # Token expiring soon (30 seconds)
    auth_manager.token_info = {
        'expires_at': time.time() + 30
    }
    assert auth_manager.is_token_expired() is True


@patch('components.playerspotify.spotify_auth.SpotifyOAuth')
def test_get_auth_url(mock_oauth_class, auth_manager):
    """Test getting authorization URL"""
    mock_oauth = MagicMock()
    mock_oauth.get_authorize_url.return_value = 'https://accounts.spotify.com/authorize?...'
    auth_manager.oauth = mock_oauth

    url = auth_manager.get_auth_url()
    assert url.startswith('https://accounts.spotify.com/authorize')
    mock_oauth.get_authorize_url.assert_called_once()


@patch('components.playerspotify.spotify_auth.SpotifyOAuth')
def test_authenticate(mock_oauth_class, auth_manager):
    """Test authentication with authorization code"""
    mock_oauth = MagicMock()
    token_info = {
        'access_token': 'new_access_token',
        'refresh_token': 'new_refresh_token',
        'expires_at': time.time() + 3600,
        'scope': 'user-read-playback-state',
        'token_type': 'Bearer'
    }
    mock_oauth.get_access_token.return_value = token_info
    auth_manager.oauth = mock_oauth

    result = auth_manager.authenticate('test_auth_code')

    assert result == token_info
    assert auth_manager.token_info == token_info
    mock_oauth.get_access_token.assert_called_once_with('test_auth_code', as_dict=True)


@patch('components.playerspotify.spotify_auth.SpotifyOAuth')
def test_refresh_token(mock_oauth_class, auth_manager):
    """Test token refresh"""
    # Set up existing token with refresh token
    old_token = {
        'access_token': 'old_access_token',
        'refresh_token': 'refresh_token_123',
        'expires_at': time.time() - 100
    }
    auth_manager.token_info = old_token

    # Mock refresh response
    new_token = {
        'access_token': 'new_access_token',
        'refresh_token': 'refresh_token_123',
        'expires_at': time.time() + 3600
    }
    mock_oauth = MagicMock()
    mock_oauth.refresh_access_token.return_value = new_token
    auth_manager.oauth = mock_oauth

    refreshed = auth_manager._refresh_token()

    assert refreshed == new_token
    # _refresh_token returns the new token but does NOT update self.token_info
    # (callers like get_access_token do: self.token_info = self._refresh_token())
    mock_oauth.refresh_access_token.assert_called_once_with('refresh_token_123')


def test_get_access_token_no_auth(auth_manager):
    """Test getting access token without authentication"""
    auth_manager.token_info = None

    with pytest.raises(ValueError, match="Not authenticated"):
        auth_manager.get_access_token()


@patch('components.playerspotify.spotify_auth.SpotifyOAuth')
def test_get_access_token_valid(mock_oauth_class, auth_manager):
    """Test getting valid access token"""
    auth_manager.token_info = {
        'access_token': 'valid_token',
        'expires_at': time.time() + 7200
    }

    token = auth_manager.get_access_token()
    assert token == 'valid_token'


@patch('components.playerspotify.spotify_auth.SpotifyOAuth')
def test_get_access_token_expired(mock_oauth_class, auth_manager):
    """Test getting access token when expired (should refresh)"""
    auth_manager.token_info = {
        'access_token': 'expired_token',
        'refresh_token': 'refresh_token',
        'expires_at': time.time() - 100
    }

    new_token = {
        'access_token': 'refreshed_token',
        'refresh_token': 'refresh_token',
        'expires_at': time.time() + 3600
    }
    mock_oauth = MagicMock()
    mock_oauth.refresh_access_token.return_value = new_token
    auth_manager.oauth = mock_oauth

    token = auth_manager.get_access_token()
    assert token == 'refreshed_token'
    mock_oauth.refresh_access_token.assert_called_once()


def test_clear_token(auth_manager, temp_credential_file):
    """Test clearing cached token"""
    # Save a token first
    auth_manager.token_info = {
        'access_token': 'test_token',
        'expires_at': time.time() + 3600
    }
    auth_manager._save_token(auth_manager.token_info)
    assert Path(temp_credential_file).exists()

    # Clear token
    auth_manager.clear_token()
    assert auth_manager.token_info is None
    assert not Path(temp_credential_file).exists()
