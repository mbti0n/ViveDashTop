#!/usr/bin/env python3
"""Open a browser so the person at the dashboard can sign in with Google."""

import argparse
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import google_auth

SUCCESS_PAGE = """<!DOCTYPE html>
<meta charset="utf-8">
<title>Signed in</title>
<p>Signed in with Google. You can close this tab and go back to the dashboard.</p>
"""

WAITING_PAGE = """<!DOCTYPE html>
<meta charset="utf-8">
<title>Finishing sign-in</title>
<p>Finishing Google sign-in…</p>
<script>
const params = new URLSearchParams(window.location.hash.slice(1));
const code = params.get("connect_code") || params.get("code");
if (code && !window.location.search.includes("connect_code=")) {
  const next = new URLSearchParams(window.location.search);
  next.set("connect_code", code);
  const state = params.get("state");
  if (state) next.set("state", state);
  window.location.replace(window.location.pathname + "?" + next.toString());
}
</script>
"""


class CallbackServer(HTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 8765), CallbackHandler)
        self.result = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self._reply(404, "Not found")
            return
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("error"):
            self.server.result = query
            self._reply(400, "<p>Google sign-in did not finish. You can close this tab.</p>")
            return
        if query.get("code") or query.get("connect_code"):
            self.server.result = query
            self._reply(200, SUCCESS_PAGE)
            return
        self._reply(200, WAITING_PAGE)

    def log_message(self, _format, *_args):
        return

    def _reply(self, status, body):
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def wait_for_browser(server, timeout):
    import time

    deadline = time.time() + timeout
    server.timeout = 1
    while time.time() < deadline:
        server.handle_request()
        if server.result:
            return server.result
    raise TimeoutError("The Google sign-in window was not completed.")


def first(query, name):
    values = query.get(name) or []
    return values[0] if values else ""


def save_auth_code(domain, client_id, client_secret, query, verifier, expected_state):
    if first(query, "state") != expected_state:
        raise google_auth.AuthError(400, "Sign-in state did not match.")
    if first(query, "error"):
        raise google_auth.AuthError(400, first(query, "error_description") or first(query, "error"))
    tokens = google_auth.exchange_authorization_code(
        domain, client_id, client_secret, first(query, "code"), verifier
    )
    if not tokens.get("refresh_token"):
        raise google_auth.AuthError(400, "Auth0 did not return a refresh token. Enable offline access and turn off refresh token rotation.")
    session = {
        "refresh_token": tokens["refresh_token"],
        "email": google_auth.email_from_id_token(tokens.get("id_token", "")),
    }
    google_auth.write_session(session)
    return session


def connect_calendar(domain, client_id, client_secret, session, server):
    """Ask Google for Calendar access when Token Vault does not have it yet."""
    account = google_auth.my_account_token(domain, client_id, client_secret, session["refresh_token"])
    state = secrets.token_urlsafe(24)
    started = google_auth.start_google_connect(
        domain, account["access_token"], google_auth.REDIRECT_URI, state
    )
    ticket = (started.get("connect_params") or {}).get("ticket")
    if not ticket:
        raise google_auth.AuthError(400, "Auth0 did not return a Google connect ticket.")
    google_auth.write_status("Allow Google Calendar\nin the browser.")
    server.result = None
    webbrowser.open(google_auth.connect_url(started["connect_uri"], ticket))
    query = wait_for_browser(server, 300)
    if first(query, "state") and first(query, "state") != state:
        raise google_auth.AuthError(400, "Calendar connect state did not match.")
    connect_code = first(query, "connect_code") or first(query, "code")
    if not connect_code:
        raise google_auth.AuthError(400, first(query, "error_description") or "Google did not return a connect code.")
    google_auth.complete_google_connect(
        domain,
        account["access_token"],
        started["auth_session"],
        connect_code,
        google_auth.REDIRECT_URI,
    )


def sign_in():
    domain, client_id, client_secret = google_auth.auth0_settings()
    if google_auth.signed_in():
        try:
            google_auth.google_access_token(google_auth.read_session())
            google_auth.write_status("")
            return
        except google_auth.AuthError:
            pass

    verifier, challenge = google_auth.pkce_pair()
    state = secrets.token_urlsafe(24)
    url = google_auth.authorize_url(domain, client_id, google_auth.REDIRECT_URI, state, challenge)
    google_auth.write_status("Sign in with Google\nCheck the browser window.")
    server = CallbackServer()
    try:
        webbrowser.open(url)
        print("Sign in with Google in the browser window.", flush=True)
        query = wait_for_browser(server, 300)
        session = save_auth_code(domain, client_id, client_secret, query, verifier, state)
        try:
            google_auth.google_access_token(session, force=True)
        except google_auth.AuthError:
            connect_calendar(domain, client_id, client_secret, session, server)
            google_auth.google_access_token(google_auth.read_session(), force=True)
    finally:
        server.server_close()
    email = (google_auth.read_session() or {}).get("email") or "Google"
    google_auth.write_status("")
    print(f"Signed in as {email}.", flush=True)


def main(argv):
    if "--check" in argv:
        try:
            google_auth.auth0_settings()
        except google_auth.AuthNotConfigured:
            return 0
        return 0 if google_auth.signed_in() else 1
    try:
        sign_in()
    except google_auth.AuthNotConfigured as exc:
        google_auth.write_status(str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    except (google_auth.AuthError, TimeoutError, OSError) as exc:
        google_auth.write_status("Google sign-in failed\nSee ~/.config/vivedash/login.log")
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 0 when a Google session is already saved")
    args = parser.parse_args()
    raise SystemExit(main(["--check"] if args.check else []))
