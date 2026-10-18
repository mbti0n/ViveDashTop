#!/usr/bin/env python3
"""WTF dashboard widget showing the user's currently playing Last.fm track."""

import json
import os
import pathlib
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request

API_URL = "https://ws.audioscrobbler.com/2.0/"
CACHE_DIR = pathlib.Path.home() / ".cache"
CACHE = CACHE_DIR / "wtf-lastfm.json"
LOCK = CACHE_DIR / "wtf-lastfm.lock"
POLL_SECONDS = 20
LOCK_STALE = 60


def load_env_file():
    """Load this config directory's .env without overriding exported values."""
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
        if not separator or not key or not key.replace("_", "").isalnum():
            continue
        try:
            parsed_value = shlex.split(value, comments=True, posix=True)
        except ValueError:
            continue
        os.environ.setdefault(key, " ".join(parsed_value))


load_env_file()

DIM = "\x1b[90m"
CYAN = "\x1b[96m"
RESET = "\x1b[0m"


def read_cache():
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return None


def write_cache(username, ts, track, failed=False):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"username": username, "ts": ts, "track": track, "failed": failed}))
    os.replace(tmp, CACHE)


def fetch_track(api_key, username):
    params = urllib.parse.urlencode({
        "method": "user.getrecenttracks",
        "user": username,
        "api_key": api_key,
        "format": "json",
        "limit": 1,
    })
    request = urllib.request.Request(f"{API_URL}?{params}", headers={"User-Agent": "wtfutil-lastfm"})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)

    if "error" in data:
        raise ValueError(data.get("message", "Last.fm API error"))
    tracks = data.get("recenttracks", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]
    if not tracks or tracks[0].get("@attr", {}).get("nowplaying") != "true":
        return None

    track = tracks[0]
    return {
        "name": track.get("name", "Unknown track"),
        "artist": track.get("artist", {}).get("#text", "Unknown artist"),
        "album": track.get("album", {}).get("#text", ""),
    }


def acquire_lock():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            os.close(os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - LOCK.stat().st_mtime < LOCK_STALE:
                    return False
                LOCK.unlink()
            except OSError:
                return False
    return False


def refresh(api_key, username):
    try:
        track = fetch_track(api_key, username)
        write_cache(username, time.time(), track)
    except Exception:  # noqa: BLE001
        cached = read_cache()
        track = cached.get("track") if cached and cached.get("username") == username else None
        write_cache(username, time.time(), track, failed=True)
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


def start_refresh(api_key, username):
    if not acquire_lock():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(pathlib.Path(__file__).resolve()), "--refresh", username],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: BLE001
        try:
            LOCK.unlink()
        except OSError:
            pass


def render(track, failed=False):
    if track:
        print(f"{CYAN}󰐊 Now playing{RESET}")
        print(f"  {track['name']}")
        print(f"  {DIM}{track['artist']}{RESET}")
        if track.get("album"):
            print(f"  {DIM}{track['album']}{RESET}")
    elif failed:
        print(f"{DIM}Last.fm unavailable.{RESET}")
    else:
        print(f"{DIM}Nothing playing.{RESET}")


def main(argv):
    if argv[:1] == ["--refresh"]:
        refresh(os.environ.get("LASTFM_API_KEY", ""), argv[1])
        return

    api_key = os.environ.get("LASTFM_API_KEY")
    username = os.environ.get("LASTFM_USERNAME")
    if not api_key or not username:
        print(f"{DIM}Set LASTFM_API_KEY and LASTFM_USERNAME.{RESET}")
        return

    cached = read_cache()
    if cached and cached.get("username") == username:
        render(cached.get("track"), cached.get("failed", False))
        if time.time() - cached.get("ts", 0) >= POLL_SECONDS:
            start_refresh(api_key, username)
        return

    start_refresh(api_key, username)
    print(f"{DIM}Loading Last.fm…{RESET}")


if __name__ == "__main__":
    main(sys.argv[1:])
