"""Gmail OAuth 2.0 Authentication Service.

Manages narrow-scope Google OAuth 2.0 authentication for the Gmail API.
Enforces the narrowest practical permission scope for V0:
https://www.googleapis.com/auth/gmail.readonly

Tokens are persisted securely in local data credentials storage with
restricted file permissions.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.config.logging import get_logger

logger = get_logger(__name__)

GMAIL_READONLY_SCOPE = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailAuthService:
    """OAuth 2.0 authentication service for Gmail API."""

    def __init__(
        self,
        credentials_dir: Path | str | None = None,
        client_secrets_filename: str = "credentials.json",
        token_filename: str = "gmail_token.json",
        scopes: list[str] | None = None,
    ) -> None:
        if credentials_dir is None:
            credentials_dir = Path(__file__).resolve().parent.parent.parent / "data" / "credentials"
        self._credentials_dir = Path(credentials_dir)
        self._client_secrets_path = self._credentials_dir / client_secrets_filename
        self._token_path = self._credentials_dir / token_filename
        self._scopes = scopes or GMAIL_READONLY_SCOPE
        self._cached_credentials: Credentials | None = None

    @property
    def scopes(self) -> list[str]:
        """Return the OAuth scopes requested by this service."""
        return list(self._scopes)

    @property
    def token_path(self) -> Path:
        """Return the path where user tokens are stored."""
        return self._token_path

    def load_credentials(self) -> Credentials | None:
        """Load stored OAuth credentials from token file if available.

        Refreshes expired credentials if a valid refresh_token exists.
        """
        if self._cached_credentials and self._cached_credentials.valid:
            return self._cached_credentials

        if not self._token_path.exists():
            logger.info("gmail_auth.no_token_file", path=str(self._token_path))
            return None

        try:
            creds = Credentials.from_authorized_user_file(str(self._token_path), self._scopes)  # type: ignore[no-untyped-call]
            if creds and creds.expired and creds.refresh_token:
                logger.info("gmail_auth.refreshing_token")
                creds.refresh(Request())
                self.save_credentials(creds)

            if creds and creds.valid:
                self._cached_credentials = creds
                logger.info("gmail_auth.credentials_loaded", valid=True)
                return creds  # type: ignore[no-any-return]
        except Exception:
            logger.exception("gmail_auth.load_failed", path=str(self._token_path))

        return None

    def authenticate_interactive(self, port: int = 0) -> Credentials:
        """Run interactive local server OAuth flow to authorize user access.

        Requires a valid Google client secrets JSON file at client_secrets_path.
        """
        if not self._client_secrets_path.exists():
            msg = (
                f"Client secrets file not found at '{self._client_secrets_path}'. "
                "Download OAuth client ID secrets from Google Cloud Console."
            )
            logger.error("gmail_auth.missing_client_secrets", path=str(self._client_secrets_path))
            raise FileNotFoundError(msg)

        logger.info("gmail_auth.starting_oauth_flow", scopes=self._scopes)
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_secrets_path), self._scopes
        )
        creds: Credentials = flow.run_local_server(port=port)
        self.save_credentials(creds)
        self._cached_credentials = creds
        logger.info("gmail_auth.oauth_flow_complete")
        return creds

    def get_credentials(self) -> Credentials:
        """Get valid credentials, raising RuntimeError if unauthenticated."""
        creds = self.load_credentials()
        if not creds or not creds.valid:
            msg = (
                "Gmail authentication is required. "
                "Call authenticate_interactive() or provide valid token file."
            )
            raise RuntimeError(msg)
        return creds

    def save_credentials(self, creds: Credentials) -> None:
        """Save OAuth token credentials securely to local filesystem.

        Enforces restricted file permissions (0600 on POSIX platforms)
        so that tokens are readable only by the owner user process.
        """
        self._credentials_dir.mkdir(parents=True, exist_ok=True)

        token_json = creds.to_json()  # type: ignore[no-untyped-call]
        self._token_path.write_text(token_json, encoding="utf-8")

        # Security constraint: set strict permissions on POSIX operating systems
        if os.name == "posix":
            try:
                os.chmod(self._token_path, 0o600)
            except OSError:
                logger.warning("gmail_auth.chmod_failed", path=str(self._token_path))

        logger.info("gmail_auth.token_saved", path=str(self._token_path))
