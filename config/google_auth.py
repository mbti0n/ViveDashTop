#!/usr/bin/env python3
"""Google sign-in through Auth0, and read-only Calendar access for the dashboard."""

import base64
import datetime as dt
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

REDIRECT_URI = "http://127.0.0.1:8765/callback"
GOOGLE_CONNECTION = "google-oauth2"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
GOOGLE_SCOPES = ["openid", "profile", "email", CALENDAR_SCOPE]
TOKEN_GRANT = "urn:auth0:params:oauth:grant-type:token-exchange:federated-connection-access-token"
FEDERATED_TOKEN = "http://auth0.com/oauth/token-type/federated-connection-access-token"
REFRESH_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:refresh_token"
MY_ACCOUNT_SCOPES = (
    "openid profile offline_access "
    "create:me:connected_accounts read:me:connected_accounts"
)

STATE_DIR = pathlib.Path.home() / ".config" / "vivedash"
SESSION_PATH = STATE_DIR / "session.json"
STATUS_PATH = STATE_DIR / "status.txt"


class AuthNotConfigured(Exception):
    """Auth0 settings are missing from config/.env."""


class SignInRequired(Exception):
    """The dashboard is open and still needs a Google sign-in."""


class AuthError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"Auth0 returned {status}: {body[:240]}")


def load_env_file():
    """Load config/.env without overriding variables already set in the environment."""
    env_file = pathlib.Path(__file__).resolve().parent / ".env"
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        os.environ.setdefault(key, value.strip().strip("\"'"))


def auth0_settings():
    load_env_file()
    domain = os.environ.get("AUTH0_DOMAIN", "").strip().removeprefix("https://").strip("/")
    client_id = os.environ.get("AUTH0_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AUTH0_CLIENT_SECRET", "").strip()
    if not domain or not client_id or not client_secret:
        raise AuthNotConfigured(
            "Add Auth0 settings\nto config/.env"
        )
    return domain, client_id, client_secret


def write_status(text):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(text.strip() + "\n")


def read_status():
    try:
        return STATUS_PATH.read_text().strip()
    except OSError:
        return ""


def sign_in_message():
    status = read_status()
    if status:
        return status
    return "Sign in with Google\nCheck the browser window."


def read_session():
    try:
        return json.loads(SESSION_PATH.read_text())
    except (OSError, ValueError):
        return None


def write_session(session):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = SESSION_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(session))
    os.chmod(temp, 0o600)
    os.replace(temp, SESSION_PATH)


def clear_session():
    try:
        SESSION_PATH.unlink()
    except OSError:
        pass


def signed_in():
    session = read_session()
    return bool(session and session.get("refresh_token"))


def pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def authorize_url(domain, client_id, redirect_uri, state, challenge):
    query = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email offline_access",
        "audience": f"https://{domain}/me/",
        "connection": GOOGLE_CONNECTION,
        "connection_scope": " ".join(GOOGLE_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"https://{domain}/authorize?{query}"


def connect_url(connect_uri, ticket):
    return f"{connect_uri}?{urllib.parse.urlencode({'ticket': ticket})}"


def email_from_id_token(id_token):
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, json.JSONDecodeError):
        return ""
    return data.get("email") or ""


def post_json(url, payload, headers=None, timeout=20):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise AuthError(exc.code, body) from exc


def post_form(url, payload, timeout=20):
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise AuthError(exc.code, body) from exc


def exchange_authorization_code(domain, client_id, client_secret, code, verifier, redirect_uri=REDIRECT_URI):
    return post_json(f"https://{domain}/oauth/token", {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
    })


def my_account_token(domain, client_id, client_secret, refresh_token):
    return post_form(f"https://{domain}/oauth/token", {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "audience": f"https://{domain}/me/",
        "scope": MY_ACCOUNT_SCOPES,
    })


def start_google_connect(domain, my_account_access_token, redirect_uri, state):
    return post_json(
        f"https://{domain}/me/v1/connected-accounts/connect",
        {
            "connection": GOOGLE_CONNECTION,
            "redirect_uri": redirect_uri,
            "state": state,
            "scopes": GOOGLE_SCOPES,
        },
        headers={"Authorization": f"Bearer {my_account_access_token}"},
    )


def complete_google_connect(domain, my_account_access_token, auth_session, connect_code, redirect_uri):
    return post_json(
        f"https://{domain}/me/v1/connected-accounts/complete",
        {
            "auth_session": auth_session,
            "connect_code": connect_code,
            "redirect_uri": redirect_uri,
        },
        headers={"Authorization": f"Bearer {my_account_access_token}"},
    )


def exchange_google_token(domain, client_id, client_secret, refresh_token):
    return post_json(f"https://{domain}/oauth/token", {
        "client_id": client_id,
        "client_secret": client_secret,
        "subject_token": refresh_token,
        "grant_type": TOKEN_GRANT,
        "subject_token_type": REFRESH_TOKEN_TYPE,
        "requested_token_type": FEDERATED_TOKEN,
        "connection": GOOGLE_CONNECTION,
    })


def google_access_token(session, force=False):
    """Return a cached Google access token, exchanging the Auth0 refresh token when needed."""
    cached = session.get("google_access_token")
    if cached and not force and session.get("google_expires_at", 0) > time.time() + 60:
        return cached
    domain, client_id, client_secret = auth0_settings()
    try:
        granted = exchange_google_token(domain, client_id, client_secret, session["refresh_token"])
    except AuthError as exc:
        if "invalid_grant" in exc.body or exc.status in (401, 403):
            clear_session()
            write_status("Sign in with Google\nThe saved session expired.")
        raise
    session["google_access_token"] = granted["access_token"]
    session["google_expires_at"] = time.time() + int(granted.get("expires_in", 300))
    write_session(session)
    return session["google_access_token"]


def events_to_tsv(items, zone):
    """Turn Calendar API events into the five-column TSV the agenda widget already parses."""
    lines = ["start_date\tstart_time\tend_date\tend_time\ttitle"]
    for item in items:
        start = item.get("start") or {}
        end = item.get("end") or {}
        title = (item.get("summary") or "(no title)").replace("\t", " ").replace("\n", " ")
        if "dateTime" in start and "dateTime" in end:
            start_at = _parse_datetime(start["dateTime"]).astimezone(zone)
            end_at = _parse_datetime(end["dateTime"]).astimezone(zone)
            lines.append(
                f"{start_at.date().isoformat()}\t{start_at.strftime('%H:%M')}\t"
                f"{end_at.date().isoformat()}\t{end_at.strftime('%H:%M')}\t{title}"
            )
        else:
            lines.append(f"{start.get('date', '')}\t\t{end.get('date', '')}\t\t{title}")
    return "\n".join(lines) + "\n"


def _parse_datetime(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_agenda_tsv(now):
    """Today and tomorrow from the signed-in Google Calendar, as TSV."""
    auth0_settings()
    session = read_session()
    if not session or not session.get("refresh_token"):
        raise SignInRequired(sign_in_message())
    try:
        token = google_access_token(session)
    except AuthError as exc:
        raise SignInRequired(sign_in_message() if not signed_in() else f"Calendar needs a new sign-in\n{exc.status}") from exc
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=2)
    query = urllib.parse.urlencode({
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
    })
    request = urllib.request.Request(
        f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            session.pop("google_access_token", None)
            session["google_expires_at"] = 0
            write_session(session)
            raise SignInRequired("Sign in with Google\nCalendar access expired.") from exc
        raise
    return events_to_tsv(payload.get("items") or [], now.tzinfo or dt.timezone.utc)
