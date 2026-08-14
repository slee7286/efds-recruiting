"""Local, read-only Gmail OAuth and incremental synchronization.

The module deliberately keeps Google tokens in the local SecretStore and keeps
message material in the local database/filesystem.  It never sends Gmail data
to the shared recruiting service.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.email_ingestion import (
    GMAIL_READONLY_SCOPE,
    GmailProvider,
    sync_gmail,
)
from quant_recruiting.local_models import LocalEmailAccount
from quant_recruiting.secrets import SecretStoreUnavailable, get_secret_store
from quant_recruiting.storage import get_local_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017


class GmailOAuthError(RuntimeError):
    """Actionable local Gmail OAuth failure."""


def _google_modules() -> tuple[Any, Any, Any, Any]:
    try:
        import importlib

        Request = importlib.import_module("google.auth.transport.requests").Request
        Credentials = importlib.import_module("google.oauth2.credentials").Credentials
        InstalledAppFlow = importlib.import_module("google_auth_oauthlib.flow").InstalledAppFlow
        build = importlib.import_module("googleapiclient.discovery").build
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional install
        raise GmailOAuthError(
            "Gmail OAuth requires optional dependencies; install `recruiting-intelligence[gmail]`."
        ) from exc
    return Request, Credentials, InstalledAppFlow, build


def _client_config(settings: Settings) -> dict[str, Any]:
    if settings.gmail_oauth_client_secret_file:
        path = settings.gmail_oauth_client_secret_file
        if not path.exists():
            raise GmailOAuthError(f"Gmail OAuth client file does not exist: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GmailOAuthError("Gmail OAuth client file is not valid JSON") from exc
        if "installed" in value:
            return cast(dict[str, Any], value)
        if "web" in value:
            return {"installed": value["web"]}
        raise GmailOAuthError("OAuth client file must contain an installed or web client")
    if settings.gmail_oauth_client_id and settings.gmail_oauth_client_secret:
        return {
            "installed": {
                "client_id": settings.gmail_oauth_client_id,
                "client_secret": settings.gmail_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://127.0.0.1"],
            }
        }
    raise GmailOAuthError(
        "configure GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET, "
        "or GOOGLE_OAUTH_CLIENT_SECRET_FILE"
    )


class _CallbackHandler(BaseHTTPRequestHandler):
    callback: dict[str, str | None] = {}
    event: threading.Event = threading.Event()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        query = parse_qs(urlparse(self.path).query)
        self.callback["code"] = query.get("code", [None])[0]
        self.callback["state"] = query.get("state", [None])[0]
        self.callback["error"] = query.get("error", [None])[0]
        self.send_response(200 if self.callback["code"] else 400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"Recruiting Assistant Gmail authorization received. You can close this window."
        )
        self.event.set()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _authorize(settings: Settings, *, open_browser: bool = True) -> tuple[Any, str]:
    _Request, _Credentials, InstalledAppFlow, _build = _google_modules()
    flow = InstalledAppFlow.from_client_config(_client_config(settings), [GMAIL_READONLY_SCOPE])
    state = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CallbackHandler)
    _CallbackHandler.callback = {}
    _CallbackHandler.event = threading.Event()
    flow.redirect_uri = f"http://127.0.0.1:{server.server_port}/oauth2callback"
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if open_browser:
            if not webbrowser.open(authorization_url):
                print("Open this Gmail authorization URL manually:", authorization_url)
        else:
            print("Open this Gmail authorization URL manually:", authorization_url)
        if not _CallbackHandler.event.wait(timeout=300):
            raise GmailOAuthError("Gmail authorization timed out")
        callback = dict(_CallbackHandler.callback)
        if callback.get("error"):
            raise GmailOAuthError(f"Gmail authorization failed: {callback['error']}")
        if not callback.get("code") or callback.get("state") != state:
            raise GmailOAuthError("Gmail OAuth state validation failed")
        flow.fetch_token(code=callback["code"])
        credentials = flow.credentials
        if not credentials.refresh_token:
            raise GmailOAuthError("Gmail did not return a refresh token; reconnect with consent")
        return credentials, flow.redirect_uri
    finally:
        server.shutdown()
        server.server_close()


def _store_credentials(settings: Settings, credentials: Any, account: str) -> None:
    try:
        store = get_secret_store(settings)
        store.set("gmail.oauth.refresh_token", str(credentials.refresh_token))
        store.set("gmail.oauth.account", account)
    except SecretStoreUnavailable as exc:
        raise GmailOAuthError(
            "an OS secret store is required for Gmail OAuth; install/configure keyring"
        ) from exc


def connect_gmail(settings: Settings | None = None, *, open_browser: bool = True) -> dict[str, Any]:
    config = settings or get_settings()
    credentials, redirect_uri = _authorize(config, open_browser=open_browser)
    _Request, _Credentials, _Flow, build = _google_modules()
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    address = str(profile.get("emailAddress", ""))
    if not address:
        raise GmailOAuthError("Gmail profile did not return an account address")
    _store_credentials(config, credentials, address)
    with get_local_session(config) as session:
        account = session.scalar(
            select(LocalEmailAccount).where(
                LocalEmailAccount.provider == "gmail", LocalEmailAccount.address == address
            )
        )
        if account is None:
            account = LocalEmailAccount(provider="gmail", address=address, status="connected")
            session.add(account)
        account.status = "connected"
        account.metadata_ = {
            **(account.metadata_ or {}),
            "oauth_scope": GMAIL_READONLY_SCOPE,
            "redirect_uri": redirect_uri,
        }
    return {
        "provider": "gmail",
        "address": address,
        "status": "connected",
        "scope": GMAIL_READONLY_SCOPE,
    }


def _credentials_and_service(settings: Settings) -> tuple[Any, Any, str]:
    _Request, Credentials, _Flow, build = _google_modules()
    try:
        store = get_secret_store(settings)
        refresh_token = store.get("gmail.oauth.refresh_token")
        account = store.get("gmail.oauth.account") or ""
    except SecretStoreUnavailable as exc:
        raise GmailOAuthError("local OS secret store is unavailable") from exc
    if not refresh_token:
        raise GmailOAuthError("Gmail is not connected; run `recruiting email connect gmail`")
    client = _client_config(settings)["installed"]
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=client["token_uri"],
        client_id=client["client_id"],
        client_secret=client["client_secret"],
        scopes=[GMAIL_READONLY_SCOPE],
    )
    if not credentials.valid:
        credentials.refresh(_Request())
    return (
        credentials,
        build("gmail", "v1", credentials=credentials, cache_discovery=False),
        account,
    )


def _bootstrap_query(settings: Settings) -> str:
    return (
        f"newer_than:{settings.gmail_lookback_days}d "
        "(application OR interview OR assessment OR recruiting OR careers OR coding)"
    )


def sync_authenticated_gmail(settings: Settings | None = None) -> dict[str, Any]:
    """Sync only new/relevant Gmail messages and persist the history cursor locally."""
    config = settings or get_settings()
    _credentials, service, account_address = _credentials_and_service(config)
    provider = GmailProvider(service)
    with get_local_session(config) as session:
        account = session.scalar(
            select(LocalEmailAccount).where(
                LocalEmailAccount.provider == "gmail", LocalEmailAccount.address == account_address
            )
        )
        if account is None:
            account = LocalEmailAccount(
                provider="gmail", address=account_address, status="connected"
            )
            session.add(account)
            session.flush()
        history_id = account.history_id
    profile = service.users().getProfile(userId="me").execute()
    latest_history = str(profile.get("historyId", "")) or None
    if history_id:
        try:
            ids = provider.list_history_message_ids(history_id)
            result = sync_gmail(provider, config, account_address=account_address, message_ids=ids)
            mode = "incremental"
        except Exception as exc:
            if "historyId" not in str(exc) and "notFound" not in str(exc):
                raise GmailOAuthError(f"Gmail incremental sync failed: {exc}") from exc
            result = sync_gmail(
                provider,
                config,
                account_address=account_address,
                query=_bootstrap_query(config),
            )
            mode = "bootstrap_after_expired_history"
    else:
        result = sync_gmail(
            provider,
            config,
            account_address=account_address,
            query=_bootstrap_query(config),
        )
        mode = "bootstrap"
    with get_local_session(config) as session:
        account = session.scalar(
            select(LocalEmailAccount).where(
                LocalEmailAccount.provider == "gmail", LocalEmailAccount.address == account_address
            )
        )
        if account:
            account.history_id = latest_history
            account.last_synced_at = datetime.now(UTC)
            if mode.startswith("bootstrap"):
                account.last_full_sync_at = account.last_synced_at
            account.status = "connected"
    return {**result, "mode": mode, "account": account_address, "history_id": latest_history}


def disconnect_gmail(settings: Settings | None = None) -> None:
    config = settings or get_settings()
    try:
        store = get_secret_store(config)
        for key in ("gmail.oauth.refresh_token", "gmail.oauth.account"):
            store.delete(key)
    except SecretStoreUnavailable:
        pass
    with get_local_session(config) as session:
        for account in session.scalars(
            select(LocalEmailAccount).where(LocalEmailAccount.provider == "gmail")
        ):
            account.status = "disconnected"
