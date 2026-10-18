#!/usr/bin/env python3
"""WTF dashboard [sports] widget: today's NHL, NFL, NBA and MLB games.

Scores come from ESPN's public scoreboard API (no key required).

The widget never blocks on the network: it renders the cached games instantly
and, when the cache is older than POLL_SECONDS, hands the refresh off to a
detached background process that updates the cache for the next render. This
keeps the module from going blank while a poll is in flight (a foreground poll
of all four leagues can take several seconds).

Layout: a coloured league heading followed by that league's games.

    NHL
    7:30 PM  TB @ CLE
    Live      PIT 2 @ COL 4  P2
    MLB
    Final     BOS 3 @ NYY 5

Inside each league the live games come first, then scheduled games, then
recently finished ones. A finished game is dropped 30 minutes after we first
see it complete. Each page contains up to PAGE_SIZE games from a single league.
All games in one league cycle through before the next league appears; pages
advance every PAGE_SECONDS seconds and wrap after the final league.

A background poll is skipped if one is already running (a lock file guards it),
so a slow or hung refresh can never stack up.
"""
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (X11; Linux x86_64) wtfutil-sports"

# Display order, as requested: NHL, NFL, NBA, MLB.
LEAGUES = (
    ("NHL", "hockey/nhl", "\x1b[94m"),       # blue
    ("NFL", "football/nfl", "\x1b[92m"),     # green
    ("NBA", "basketball/nba", "\x1b[91m"),   # red
    ("MLB", "baseball/mlb", "\x1b[93m"),     # yellow
)
LEAGUE_INDEX = {name: i for i, (name, _, _) in enumerate(LEAGUES)}
COLORS = {name: color for name, _, color in LEAGUES}
LEAGUE_ICONS = {"NFL": "", "NHL": "󰡺", "MLB": "", "NBA": ""}

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={date}"

CACHE_DIR = pathlib.Path.home() / ".cache"
CACHE = CACHE_DIR / "wtf-sports.json"
LOCK = CACHE_DIR / "wtf-sports.lock"

POLL_SECONDS = 30        # minimum seconds between API polls (ESPN is generous)
RETRY_AFTER = 30         # shorter wait before retrying after a failed poll
PAGE_SIZE = 5            # games per page
PAGE_SECONDS = 8         # seconds each page is shown
HIDE_AFTER_FINAL = 30 * 60
LOCK_STALE = 90          # assume a lock this old belongs to a dead refresh

# Typical wall-clock length of a game, used only to hide a finished game when
# we never actually observed it finish (e.g. the cache was cleared mid-game).
GAME_MINUTES = {"NHL": 165, "NBA": 165, "NFL": 210, "MLB": 195}

RESET = "\x1b[0m"
DIM = "\x1b[90m"


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def parse_utc(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def fmt_time(iso):
    return parse_utc(iso).astimezone(TZ).strftime("%-I:%M %p")


def live_label(game):
    """Compact in-progress label: P2 for hockey, Q2 for NBA/NFL, T5/B7 for MLB."""
    league = game["league"]
    period = game.get("period")
    if league == "NHL":
        return f"P{period}" if period else "Live"
    if league in ("NBA", "NFL"):
        return f"Q{period}" if period else "Live"
    detail = game.get("detail") or "Live"
    half = re.match(r"(Top|Bot|End|Mid)\w*\s*(\d+)", detail)
    return f"{half.group(1)[0].upper()}{half.group(2)}" if half else detail


def final_label(detail):
    """"Final" -> "Final", "Final/OT" -> "F/OT"."""
    if detail.startswith("Final") and len(detail) > 5:
        return "F" + detail[5:]
    return "Final"


def parse_event(league, event):
    """Flatten the bits of an ESPN event we need into a JSON-able dict."""
    comp = event["competitions"][0]
    sides = {team["homeAway"]: team for team in comp["competitors"]}
    away, home = sides["away"], sides["home"]

    status = comp["status"]
    stype = status["type"]
    return {
        "league": league,
        "id": event.get("id"),
        "start": event.get("date", ""),
        "state": stype.get("state", "pre"),
        "completed": bool(stype.get("completed")),
        "detail": stype.get("detail", ""),
        "period": status.get("period"),
        "away": away["team"]["abbreviation"],
        "home": home["team"]["abbreviation"],
        "away_score": away.get("score"),
        "home_score": home.get("score"),
    }


def read_cache():
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return None


def write_cache(date_str, ts, games, seen, failed):
    """Write atomically so a reader never sees a half-written cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"date": date_str, "ts": ts, "games": games, "seen": seen, "failed": failed}))
    os.replace(tmp, CACHE)


def next_poll_ts(failed):
    """The cache timestamp to store: 'now' on success, sooner on failure."""
    return time.time() - POLL_SECONDS + RETRY_AFTER if failed else time.time()


def poll(date_str, cached):
    """Fetch every league. Returns ({league: [game]}, {game_id: first_final_ts}, failed)."""
    same_day = bool(cached) and cached.get("date") == date_str
    prev_games = cached.get("games", {}) if same_day else {}
    seen = dict(cached.get("seen", {})) if same_day else {}

    games = {}
    failed = False
    now = time.time()
    for league, path, _color in LEAGUES:
        try:
            data = fetch_json(SCOREBOARD.format(path=path, date=date_str))
        except Exception:  # noqa: BLE001
            failed = True
            games[league] = prev_games.get(league, [])
            continue
        parsed = []
        for event in data.get("events", []):
            try:
                parsed.append(parse_event(league, event))
            except (KeyError, IndexError, TypeError):
                continue
        games[league] = parsed

    # Remember when each still-listed completed game was first seen final, and
    # forget the ids that are no longer around.
    present = {g.get("id") for league_games in games.values() for g in league_games}
    seen = {gid: ts for gid, ts in seen.items() if gid in present}
    for league_games in games.values():
        for game in league_games:
            if game["completed"] and game.get("id") and game["id"] not in seen:
                seen[game["id"]] = now

    return games, seen, failed


def refresh(date_str):
    """Background entry point: poll, write the cache, release the lock."""
    try:
        games, seen, failed = poll(date_str, read_cache())
        write_cache(date_str, next_poll_ts(failed), games, seen, failed)
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


def acquire_lock():
    """Create the lock, or return False if a live refresh already holds it."""
    for _ in range(2):
        try:
            os.close(os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - LOCK.stat().st_mtime < LOCK_STALE:
                    return False
            except OSError:
                continue
            try:
                LOCK.unlink()  # stale lock from a refresh that died
            except OSError:
                return False
    return False


def start_refresh(date_str):
    """Kick off a detached refresh. True if one is (now) running."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not acquire_lock():
        return True
    try:
        subprocess.Popen(
            [sys.executable, str(pathlib.Path(__file__).resolve()), "--refresh", date_str],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:  # noqa: BLE001
        try:
            LOCK.unlink()
        except OSError:
            pass
        return False


def hide_after(game, seen):
    """Epoch after which a completed game should be dropped, or None if still shown."""
    if not game["completed"]:
        return None
    observed = seen.get(game.get("id"))
    if observed:
        return observed + HIDE_AFTER_FINAL
    try:
        start = parse_utc(game["start"])
    except ValueError:
        return None
    length = dt.timedelta(minutes=GAME_MINUTES.get(game["league"], 180))
    return (start + length).timestamp() + HIDE_AFTER_FINAL


def select(games, seen, now):
    """Visible games, ordered by league then live -> scheduled -> finished."""
    rank = {"in": 0, "pre": 1, "post": 2}
    visible = []
    for league, _path, _color in LEAGUES:
        for game in games.get(league, []):
            cutoff = hide_after(game, seen)
            if cutoff is not None and now > cutoff:
                continue
            visible.append(game)
    visible.sort(key=lambda g: (LEAGUE_INDEX.get(g["league"], 99), rank.get(g["state"], 3), g.get("start", "")))
    return visible


def game_line(game):
    away, home = game["away"], game["home"]
    a_score, h_score = game["away_score"], game["home_score"]

    if game["state"] == "in":
        return f"{'Live':>8}  {away} {a_score} @ {home} {h_score}  {live_label(game)}"
    if game["state"] == "post":
        if game["completed"]:
            return f"{final_label(game['detail']):<8}  {away} {a_score} @ {home} {h_score}"
        return f"{game['detail']:<8}  {away} @ {home}"
    return f"{fmt_time(game['start']):>8}  {away} @ {home}"


def render_pages(games):
    """Create pages of up to PAGE_SIZE games without splitting league order."""
    pages = []
    for league, _path, _color in LEAGUES:
        league_games = [game for game in games if game["league"] == league]
        pages.extend(
            league_games[offset:offset + PAGE_SIZE]
            for offset in range(0, len(league_games), PAGE_SIZE)
        )
    return pages


def render_page(games):
    """Render one league-specific page."""
    lines = []
    if games:
        league = games[0]["league"]
        lines.append(f"{LEAGUE_ICONS[league]} {COLORS[league]}{league}{RESET}")
        lines.extend(game_line(game) for game in games)
    return lines


def render(games, seen, failed, now):
    visible = select(games, seen, now)
    if not visible:
        print(f"{DIM}{'Scores unavailable.' if failed else 'No games today.'}{RESET}")
        return
    pages = render_pages(visible)
    page = int(now // PAGE_SECONDS) % len(pages) if len(pages) > 1 else 0
    for line in render_page(pages[page]):
        print(line)


def main(argv):
    if argv[:1] == ["--refresh"]:
        refresh(argv[1])
        return

    date_str = dt.datetime.now(TZ).strftime("%Y%m%d")
    cached = read_cache()

    if cached and cached.get("date") == date_str:
        # Never block: render what we have, refresh in the background when stale.
        render(cached.get("games", {}), cached.get("seen", {}), cached.get("failed", False), time.time())
        if time.time() - cached.get("ts", 0) >= POLL_SECONDS:
            start_refresh(date_str)
        return

    # Nothing usable for today yet (first run, or the day just rolled over).
    if start_refresh(date_str):
        print(f"{DIM}Loading scores...{RESET}")
        return
    # Could not detach a worker; fall back to a one-off blocking fetch.
    games, seen, failed = poll(date_str, cached)
    write_cache(date_str, next_poll_ts(failed), games, seen, failed)
    render(games, seen, failed, time.time())


if __name__ == "__main__":
    main(sys.argv[1:])
