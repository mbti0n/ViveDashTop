#!/usr/bin/env python3
"""WTF dashboard [info] widget showing upcoming events and a short briefing."""
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import google_auth

google_auth.load_env_file()

CITY = "Orlando"
TZ = ZoneInfo("America/New_York")
UA = "curl/8.0"

WEATHER_CACHE = pathlib.Path.home() / ".cache" / "wtf-weather.txt"
WEATHER_MAX_AGE = 15 * 60  # seconds
AGENDA_CACHE = pathlib.Path.home() / ".cache" / "wtf-agenda.tsv"
AGENDA_MAX_AGE = 5 * 60
AGENDA_LIMIT = 2  # maximum number of events shown
INFO_WIDTH = 28  # leave room for the widget border
BRIEFING_CACHE = pathlib.Path.home() / ".cache" / "wtf-briefing.json"
BRIEFING_LOCK = pathlib.Path.home() / ".cache" / "wtf-briefing.lock"
BRIEFING_MAX_AGE = 20 * 60
BRIEFING_RETRY = 5 * 60
BRIEFING_PROMPT_VERSION = 4
SPORTS_CACHE = pathlib.Path.home() / ".cache" / "wtf-sports.json"
LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
NWS_POINT = "https://api.weather.gov/points/28.5383,-81.3792"
NWS_ALERTS = "https://api.weather.gov/alerts/active?point=28.5383,-81.3792"
NWS_UA = "wtf-personal-dashboard (https://github.com/wtfutil/wtf)"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
BRIEFING_ICONS = {"weather": "\uf185", "music": "\uf001"}
SPORTS_ICONS = {"NFL": "", "NHL": "󰡺", "MLB": "", "NBA": ""}
GAS_CACHE = pathlib.Path.home() / ".cache" / "wtf-gas.txt"
GAS_MAX_AGE = 60 * 60
GAS_URL = "https://jacobschulman.github.io/gas-tracker/api/v1/latest.json"
# Round to whole cents: 4.1903 -> 4.19.
GAS_FILTER = '"Regular: $" + (.states.FL.regular * 100 | round / 100 | tostring) + "/gal"'

CURL = shutil.which("curl") or "/usr/bin/curl"
JQ = shutil.which("jq") or "/usr/bin/jq"

# 5x7 dot-matrix glyphs ('1' = lit dot).
FONT = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["000", "000", "010", "000", "010", "000", "000"],
}

# Braille bit value for each (column, row) inside a 2x4 character cell.
BRAILLE = [[0x01, 0x02, 0x04, 0x40], [0x08, 0x10, 0x20, 0x80]]

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def render_dots(text, gap=1):
    """Render `text` from FONT into braille dot-matrix lines."""
    glyphs = [FONT.get(ch, FONT[":"]) for ch in text]
    height = max(len(g) for g in glyphs)
    width = sum(len(g[0]) for g in glyphs) + gap * (len(glyphs) - 1)

    grid = [[0] * width for _ in range(height)]
    x = 0
    for glyph in glyphs:
        gw = len(glyph[0])
        for y, row in enumerate(glyph):
            for dx, bit in enumerate(row):
                if bit == "1":
                    grid[y][x + dx] = 1
        x += gw + gap

    lines = []
    for cy in range(0, height, 4):
        line = ""
        for cx in range(0, width, 2):
            bits = 0
            for dx in range(2):
                for dy in range(4):
                    px, py = cx + dx, cy + dy
                    if px < width and py < height and grid[py][px]:
                        bits |= BRAILLE[dx][dy]
            line += chr(0x2800 + bits) if bits else " "
        lines.append(line.rstrip())
    return lines


def clock_lines(now):
    """12-hour dot-matrix clock, rounded to the minute."""
    rounded = now.replace(second=0, microsecond=0)
    lines = render_dots(rounded.strftime("%-I:%M"))
    lines[-1] += "   " + rounded.strftime("%p")
    return lines


def weather():
    """One-line current weather: condition emoji + temperature in Fahrenheit."""
    # Reuse a cached reading so the frequent clock refresh doesn't hammer
    # wttr.in (and so we still show something when offline).
    if WEATHER_CACHE.exists() and time.time() - WEATHER_CACHE.stat().st_mtime < WEATHER_MAX_AGE:
        return WEATHER_CACHE.read_text().strip()

    try:
        url = f"https://wttr.in/{CITY}?format=%c+%t&u"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
        # wttr.in returns e.g. "\u2600\ufe0f  +81\u00b0F"; drop the "+" sign and
        # collapse the padding spaces.
        text = " ".join(ANSI.sub("", text).replace("+", "").split())
        WEATHER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        WEATHER_CACHE.write_text(text)
        return text
    except Exception:  # noqa: BLE001
        if WEATHER_CACHE.exists():
            return WEATHER_CACHE.read_text().strip()
        raise


def gas():
    """Florida's average regular gas price, cached for an hour."""
    if GAS_CACHE.exists() and time.time() - GAS_CACHE.stat().st_mtime < GAS_MAX_AGE:
        return GAS_CACHE.read_text().strip()

    try:
        curl = subprocess.run([CURL, "-fsS", GAS_URL], capture_output=True, text=True, timeout=20)
        jq = subprocess.run(
            [JQ, "-r", GAS_FILTER], input=curl.stdout, capture_output=True, text=True, timeout=20
        )
        text = jq.stdout.strip()
        GAS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GAS_CACHE.write_text(text)
        return text
    except Exception:  # noqa: BLE001
        if GAS_CACHE.exists():
            return GAS_CACHE.read_text().strip()
        raise


def agenda_tsv():
    """Today's and tomorrow's Google Calendar agenda as TSV, cached briefly."""
    if AGENDA_CACHE.exists() and time.time() - AGENDA_CACHE.stat().st_mtime < AGENDA_MAX_AGE:
        return AGENDA_CACHE.read_text()

    text = google_auth.fetch_agenda_tsv(dt.datetime.now(TZ))
    AGENDA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    AGENDA_CACHE.write_text(text)
    return text


def fmt_12h(hhmm):
    """'07:30' -> '7:30am' (always 12-hour, no leading zero)."""
    return dt.datetime.strptime(hhmm, "%H:%M").strftime("%-I:%M%p").lower()


def agenda(now):
    """The next few upcoming events for today and tomorrow.

    All-day events and events that have already finished are dropped; events in
    progress are kept. Each event renders as two "│"-prefixed lines — the
    title, then "start time - end time" — with a blank line between events.
    """
    rows = []
    for line in agenda_tsv().splitlines():
        fields = line.split("\t")
        if len(fields) != 5 or fields[0] == "start_date":
            continue
        start_date, start_time, end_date, end_time, title = fields
        if not start_time:
            continue  # Ignore all-day events.
        start = dt.datetime.fromisoformat(f"{start_date}T{start_time}").replace(tzinfo=TZ)
        end = dt.datetime.fromisoformat(f"{end_date}T{end_time}").replace(tzinfo=TZ)
        if end < now:
            continue
        rows.append((start, end, title.strip()))

    rows.sort(key=lambda row: row[0])
    rows = rows[:AGENDA_LIMIT]

    blocks = []
    for start, end, title in rows:
        title_lines = wrap_cells(title, INFO_WIDTH, first_prefix="│", continuation_prefix="│")
        title_lines.append(f"│{fmt_12h(start.strftime('%H:%M'))} - {fmt_12h(end.strftime('%H:%M'))}")
        blocks.append("\n".join(title_lines))
    return "\n\n".join(blocks)


def cell_width(char):
    if unicodedata.combining(char) or char in ("\ufe0e", "\ufe0f", "\u200d"):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def wrap_cells(text, width, first_prefix="", continuation_prefix="  "):
    """Wrap text to terminal columns, preserving all words and prefixes."""
    words = " ".join(str(text).replace("\n", " ").split()).split(" ")
    lines = []
    prefix = first_prefix
    line = prefix
    for word in words:
        separator = " " if line != prefix and not line.endswith(" ") else ""
        candidate = f"{line}{separator}{word}"
        if display_cells(candidate) <= width:
            line = candidate
            continue
        if line != prefix:
            lines.append(line.rstrip())
        prefix = continuation_prefix
        line = prefix
        for char in word:
            if display_cells(line) + cell_width(char) > width and line != prefix:
                lines.append(line)
                line = prefix
            line += char
    if line != prefix or not lines:
        lines.append(line.rstrip())
    return lines


def display_cells(text):
    return sum(cell_width(char) for char in text)


def truncate_cells(text, width):
    """Truncate text by terminal columns, reserving the last cell for an ellipsis."""
    output = ""
    used = 0
    for char in text.replace("\n", " ").replace("\r", " "):
        if unicodedata.combining(char) or char in ("\ufe0e", "\ufe0f", "\u200d"):
            output += char
            continue
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + char_width > width:
            return output.rstrip() + "…"
        output += char
        used += char_width
    return output


def read_briefing_cache():
    try:
        return json.loads(BRIEFING_CACHE.read_text())
    except (OSError, ValueError):
        return None


def get_gemini_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    # WTF does not load .env itself; read only the Gemini key, never print it.
    for env_path in (pathlib.Path(__file__).with_name(".env"), pathlib.Path.home() / ".config/wtf/.env"):
        try:
            for line in env_path.read_text().splitlines():
                name, separator, value = line.partition("=")
                if separator and name.strip() == "GEMINI_API_KEY":
                    return value.strip().strip("\"'")
        except OSError:
            continue
    return ""


def fetch_json(url, headers=None, timeout=12):
    request = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def weather_context():
    """Return noteworthy Orlando NWS alerts or near-term rain information."""
    context = []
    try:
        alerts = fetch_json(NWS_ALERTS, {"User-Agent": NWS_UA})
        features = alerts.get("features", [])
        severity = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}
        features.sort(key=lambda feature: severity.get(feature.get("properties", {}).get("severity"), 5))
        for feature in features[:2]:
            props = feature.get("properties", {})
            title = props.get("headline") or props.get("event")
            if title:
                context.append({"source": "weather", "text": f"NWS alert: {title}"})
    except Exception:  # noqa: BLE001
        pass

    if context:
        return context
    try:
        point = fetch_json(NWS_POINT, {"User-Agent": NWS_UA})
        forecast_url = point["properties"]["forecastHourly"]
        forecast = fetch_json(forecast_url, {"User-Agent": NWS_UA})
        periods = forecast.get("properties", {}).get("periods", [])
        if periods:
            period = periods[0]
            chance = period.get("probabilityOfPrecipitation", {}).get("value")
            description = period.get("shortForecast", "")
            if (chance is not None and chance >= 30) or "rain" in description.lower() or "shower" in description.lower():
                context.append({
                    "source": "weather",
                    "text": f"{description}; precipitation chance {chance if chance is not None else 'unknown'}%.",
                })
    except Exception:  # noqa: BLE001
        pass
    return context


def sports_context():
    try:
        cache = json.loads(SPORTS_CACHE.read_text())
    except (OSError, ValueError):
        return []
    if cache.get("date") != dt.datetime.now(TZ).strftime("%Y%m%d"):
        return []
    favorites = {name.strip().upper() for name in os.environ.get("SPORTS_FAVORITES", "").split(",") if name.strip()}
    candidates = []
    for league, games in cache.get("games", {}).items():
        for game in games:
            away, home = game.get("away", "?"), game.get("home", "?")
            favorite = away in favorites or home in favorites
            state = game.get("state")
            if state == "in":
                text = f"Live: {away} {game.get('away_score', 0)}–{game.get('home_score', 0)} {home} ({game.get('detail', '')})"
                rank = 0
            elif state == "pre":
                start = game.get("start", "")
                try:
                    when = dt.datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(TZ).strftime("%-I:%M %p")
                except ValueError:
                    when = "today"
                text = f"{away} vs {home} at {when}"
                rank = 1
            elif state == "post":
                text = f"Final: {away} {game.get('away_score', 0)}–{game.get('home_score', 0)} {home}"
                rank = 2
            else:
                continue
            candidates.append((not favorite, rank, league, text))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [
        {"source": "sports", "league": league, "text": text}
        for _, _, league, text in candidates[:8]
    ]


def music_context():
    api_key = os.environ.get("LASTFM_API_KEY")
    username = os.environ.get("LASTFM_USERNAME")
    if not api_key or not username:
        return []
    today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    params = urllib.parse.urlencode({
        "method": "user.getrecenttracks", "user": username, "api_key": api_key,
        "format": "json", "from": int(today.timestamp()), "to": int(time.time()), "limit": 200,
    })
    try:
        data = fetch_json(f"{LASTFM_API_URL}?{params}", {"User-Agent": "wtfutil-info"}, timeout=10)
        tracks = data.get("recenttracks", {}).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
        counts = {}
        for track in tracks:
            title = track.get("name", "").strip()
            artist = track.get("artist", {}).get("#text", "").strip()
            if not title or not track.get("date", {}).get("uts"):
                continue
            key = (title, artist)
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return []
        (title, artist), plays = max(counts.items(), key=lambda item: item[1])
        return [{"source": "music", "text": f"Most played today: {title} — {artist} ({plays} plays)"}]
    except Exception:  # noqa: BLE001
        return []


def generate_briefing(context):
    if not context:
        return []
    key = get_gemini_key()
    if not key:
        raise RuntimeError("Gemini key unavailable")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={urllib.parse.quote(key)}"

    def ask(prompt):
        request = urllib.request.Request(
            url,
            data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
        text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        items = json.loads(text)
        points = []
        for item in items:
            source = item.get("source")
            point = " ".join(str(item.get("text", "")).split())
            if source == "sports":
                point = re.sub(r"^(?:NFL|NHL|MLB|NBA)\s+today:\s*", "", point, flags=re.IGNORECASE)
            if source in BRIEFING_ICONS and point:
                points.append({"source": source, "text": point})
            elif source == "sports" and point:
                league = str(item.get("league", "")).upper()
                if league not in SPORTS_ICONS:
                    match = re.search(r"\b(NFL|NHL|MLB|NBA)\b", point.upper())
                    league = match.group(1) if match else ""
                if league in SPORTS_ICONS:
                    points.append({"source": source, "league": league, "text": point})
            if len(points) == 3:
                break
        return points

    context_json = json.dumps(context, ensure_ascii=False)
    instructions = (
        "Choose the 3 most important timely points from this data, allowing multiple points from one source. "
        "If fewer than 3 verified facts are available, return fewer. Use only stated facts; never invent details. "
        "Write in normal sentence case: capitalize sentence starts and proper nouns only, not random words. "
        "Each point must fit in at most 2 lines of a 28-column pane: limit its text to 50 terminal cells. "
        "For sports points, include the exact league field (NFL, NHL, MLB, or NBA) from the source. "
        "For scheduled games, do not prefix the matchup with the league name or the word 'today'. "
        "Do not add a city or location to weather points. "
        "Keep wording short and simple. Return JSON only as an array of objects with 'source' "
        "(weather, sports, or music), 'text', and 'league' for sports points.\n"
    )
    points = ask(instructions + f"Data: {context_json}")

    def fits(point):
        return len(wrap_cells(
            point["text"], INFO_WIDTH,
            first_prefix=f"{briefing_icon(point)} ",
            continuation_prefix="  ",
        )) <= 2

    if any(not fits(point) for point in points):
        revision = (
            "Rewrite these same points shorter so every point fits at most 2 lines in a 28-column pane. "
            "Preserve all important facts, use normal sentence case, and do not drop a point. "
            "Keep the exact league field on sports points and add no location to weather points. "
            "Return the same JSON array schema with source, text, and league for sports.\n"
            f"Original data: {context_json}\nPoints: {json.dumps(points, ensure_ascii=False)}"
        )
        points = ask(revision)
    if any(not fits(point) for point in points):
        raise ValueError("Gemini points do not fit the info pane")
    return points


def refresh_briefing():
    previous = read_briefing_cache() or {}
    try:
        context = weather_context() + sports_context() + music_context()
        points = generate_briefing(context)
        result = {
            "points": points,
            "message": "" if points else "No notable updates",
            "next_refresh": time.time() + BRIEFING_MAX_AGE,
            "version": BRIEFING_PROMPT_VERSION,
        }
    except Exception:  # noqa: BLE001
        old_points = previous.get("points", [])
        result = {
            "points": old_points,
            "message": "" if old_points else "Summary unavailable",
            "next_refresh": time.time() + BRIEFING_RETRY,
            "version": BRIEFING_PROMPT_VERSION,
        }
    BRIEFING_CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BRIEFING_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False))
    os.replace(tmp, BRIEFING_CACHE)


def start_briefing_refresh():
    BRIEFING_CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(BRIEFING_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            if time.time() - BRIEFING_LOCK.stat().st_mtime > 180:
                BRIEFING_LOCK.unlink()
                return start_briefing_refresh()
        except OSError:
            pass
        return
    os.close(fd)
    try:
        subprocess.Popen(
            [sys.executable, str(pathlib.Path(__file__).resolve()), "--refresh-briefing"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: BLE001
        try:
            BRIEFING_LOCK.unlink()
        except OSError:
            pass


def briefing_icon(point):
    if point["source"] == "sports":
        return SPORTS_ICONS[point["league"]]
    return BRIEFING_ICONS[point["source"]]


def briefing_lines():
    cached = read_briefing_cache() or {}
    if (cached.get("version") != BRIEFING_PROMPT_VERSION
            or cached.get("next_refresh", 0) <= time.time()):
        start_briefing_refresh()
    points = cached.get("points", [])
    if points:
        lines = []
        for point in points[:3]:
            text = re.sub(
                r"^(?:NFL|NHL|MLB|NBA)\s+today:\s*", "", point["text"], flags=re.IGNORECASE
            )
            wrapped = wrap_cells(
                text,
                INFO_WIDTH,
                first_prefix=f"{briefing_icon(point)} ",
                continuation_prefix="  ",
            )
            if len(wrapped) <= 2:
                lines.extend(wrapped)
        if lines:
            return lines
    return [truncate_cells(cached.get("message") or "\uf110 Building briefing…", INFO_WIDTH)]


def main():
    if sys.argv[1:] == ["--refresh-briefing"]:
        try:
            refresh_briefing()
        finally:
            try:
                BRIEFING_LOCK.unlink()
            except OSError:
                pass
        return

    now = dt.datetime.now(TZ)
    out = []
    try:
        events = agenda(now)
        if events:
            out.extend(events.splitlines())
    except (google_auth.SignInRequired, google_auth.AuthNotConfigured) as exc:
        out.extend(truncate_cells(line, INFO_WIDTH) for line in str(exc).splitlines())
    except Exception as exc:  # noqa: BLE001
        out.append(truncate_cells(f"Agenda unavailable: {exc}", INFO_WIDTH))
    if out:
        out.append("")
    out.extend(briefing_lines())
    print("\n".join(out))


if __name__ == "__main__":
    main()
