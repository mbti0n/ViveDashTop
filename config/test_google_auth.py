#!/usr/bin/env python3
"""Checks for the Google sign-in helpers that do not need a network."""

import datetime as dt
import os
import pathlib
import tempfile
import unittest
from zoneinfo import ZoneInfo

import google_auth


class GoogleAuthTests(unittest.TestCase):
    def test_authorize_url_goes_straight_to_google_calendar(self):
        url = google_auth.authorize_url(
            "vivedash.us.auth0.com",
            "client-id",
            google_auth.REDIRECT_URI,
            "state-value",
            "challenge-value",
        )
        self.assertIn("https://vivedash.us.auth0.com/authorize?", url)
        self.assertIn("connection=google-oauth2", url)
        self.assertIn("calendar.events.readonly", url)
        self.assertIn("audience=https%3A%2F%2Fvivedash.us.auth0.com%2Fme%2F", url)
        self.assertIn("code_challenge=challenge-value", url)
        self.assertIn("code_challenge_method=S256", url)

    def test_pkce_challenge_matches_the_verifier(self):
        import base64
        import hashlib

        verifier, challenge = google_auth.pkce_pair()
        digest = hashlib.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        self.assertEqual(challenge, expected)
        self.assertNotIn("=", verifier)

    def test_timed_event_becomes_agenda_tsv_in_local_time(self):
        zone = ZoneInfo("America/New_York")
        text = google_auth.events_to_tsv(
            [{
                "summary": "Standup",
                "start": {"dateTime": "2026-10-18T18:00:00Z"},
                "end": {"dateTime": "2026-10-18T18:30:00Z"},
            }],
            zone,
        )
        self.assertIn("2026-10-18\t14:00\t2026-10-18\t14:30\tStandup", text)

    def test_all_day_event_has_empty_times(self):
        text = google_auth.events_to_tsv(
            [{
                "summary": "Holiday",
                "start": {"date": "2026-10-18"},
                "end": {"date": "2026-10-19"},
            }],
            dt.timezone.utc,
        )
        self.assertIn("2026-10-18\t\t2026-10-19\t\tHoliday", text)

    def test_missing_session_asks_for_google_sign_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            google_auth.SESSION_PATH = pathlib.Path(tmp) / "session.json"
            google_auth.STATUS_PATH = pathlib.Path(tmp) / "status.txt"
            os.environ["AUTH0_DOMAIN"] = "example.auth0.com"
            os.environ["AUTH0_CLIENT_ID"] = "client-id"
            os.environ["AUTH0_CLIENT_SECRET"] = "client-secret"
            with self.assertRaises(google_auth.SignInRequired) as caught:
                google_auth.fetch_agenda_tsv(dt.datetime.now(dt.timezone.utc))
        self.assertIn("Sign in with Google", str(caught.exception))

    def test_email_comes_from_the_id_token_payload(self):
        import base64
        import json

        payload = base64.urlsafe_b64encode(json.dumps({"email": "ada@ufl.edu"}).encode()).decode().rstrip("=")
        self.assertEqual(google_auth.email_from_id_token(f"aaa.{payload}.zzz"), "ada@ufl.edu")


if __name__ == "__main__":
    unittest.main()
