# Local Gmail OAuth

V13 uses Google's installed-application OAuth flow with the read-only scope:

`https://www.googleapis.com/auth/gmail.readonly`

The assistant never asks for a Gmail password and never scrapes Gmail's web UI.
The refresh token is stored through the local OS-backed `SecretStore`; message
content, cursors, and extracted recruiting events remain in local SQLite/files.

Install the optional integration dependencies:

```text
pip install "recruiting-intelligence[gmail]"
```

Configure a Google OAuth desktop client using either:

```text
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
```

or `GOOGLE_OAUTH_CLIENT_SECRET_FILE` pointing to the downloaded client JSON.
Never commit that file. Then run:

```text
recruiting email connect gmail
recruiting email status
recruiting email sync
```

The first sync is constrained by `GMAIL_LOOKBACK_DAYS` (default 60) and
recruiting-oriented Gmail search terms. Later syncs use Gmail history IDs. If a
history cursor expires, the client performs a bounded bootstrap again. Sync is
idempotent and does not send, delete, archive, or mark messages.

If authorization is revoked, disconnect and reconnect. OAuth callback listeners
bind to loopback only, use a random state value, shut down after one callback,
and never log tokens.
