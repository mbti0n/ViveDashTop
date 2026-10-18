#!/usr/bin/env python3
"""Compact clock and weather header for the top dashboard pane."""

import datetime as dt
import json
import os
import pathlib
import re
import time
import unicodedata
import urllib.request
from info import clock_lines


# The top widget spans two 32-column grid cells; leave room for its borders.
PANE_WIDTH = 58
CALENDAR_WIDTH = PANE_WIDTH
WEATHER_CACHE = pathlib.Path.home() / ".cache" / "wtf-weather-summary.json"
WEATHER_LOCK = pathlib.Path.home() / ".cache" / "wtf-weather-summary.lock"
WEATHER_CACHE_SECONDS = 15 * 60
WEATHER_RETRY_SECONDS = 60
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
DIM = "\x1b[90m"
WHITE = "\x1b[97m"
RESET = "\x1b[0m"


def display_width(text):
    """Approximate terminal-cell width for the symbols used in this widget."""
    text = ANSI_ESCAPE.sub("", text)
    width = 0
    for char in text:
        if unicodedata.combining(char) or char in ("\ufe0e", "\ufe0f", "\u200d"):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def fit_left(text, width):
    """Keep a left-aligned string within a terminal-cell width."""
    result = ""
    used = 0
    index = 0
    while index < len(text):
        escape = ANSI_ESCAPE.match(text, index)
        if escape:
            result += escape.group()
            index = escape.end()
            continue
        char = text[index]
        char_width = display_width(char)
        if used + char_width > width:
            break
        result += char
        used += char_width
        index += 1
    return result


def calendar_lines(now):
    days = [now.date() + dt.timedelta(days=offset) for offset in range(7)]
    weekdays = []
    day_numbers = []
    for day in days:
        weekday = f"{day.strftime('%a')[:2]:>3}"
        field = f"{day.day:>3}"
        color = WHITE if day == now.date() else DIM
        weekday = f"{color}{weekday}{RESET}"
        field = f"{color}{field}{RESET}"
        weekdays.append(weekday)
        day_numbers.append(field)
    return (
        " ".join(weekdays).rstrip(),
        " ".join(day_numbers),
    )


def left_and_right(left, right):
    right = fit_left(right, CALENDAR_WIDTH)
    room = max(0, CALENDAR_WIDTH - display_width(right) - 1)
    left = fit_left(left, room)
    gap = CALENDAR_WIDTH - display_width(left) - display_width(right)
    return f"{left}{' ' * gap}{right}"


def weather_summary():
    now = time.time()
    try:
        cached = json.loads(WEATHER_CACHE.read_text())
    except (OSError, ValueError):
        cached = {}

    if cached.get("next_check", 0) > now:
        return cached.get("icon", ""), cached.get("temperature", "Weather unavailable")

    WEATHER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(WEATHER_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # Another refresh is already fetching; keep showing the previous value.
        return cached.get("icon", ""), cached.get("temperature", "Weather unavailable")

    os.close(fd)
    try:
        request = urllib.request.Request(
            "https://wttr.in/?format=j1&u", headers={"User-Agent": "curl/8.0"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)

        current = data["current_condition"][0]
        temp = current.get("temp_F")
        if temp is None:
            today = data["weather"][0]
            now_hour = dt.datetime.now().hour
            hourly = min(
                today["hourly"],
                key=lambda hour: abs(int(hour["time"]) // 100 - now_hour),
            )
            temp = hourly["tempF"]
        condition = current["weatherDesc"][0]["value"].strip()
        description = condition.lower()
        if "hurricane" in description or "cyclone" in description:
            icon = ""
        elif any(word in description for word in ("thunder", "storm")):
            icon = ""
        elif any(word in description for word in ("snow", "sleet", "ice")):
            icon = "🌨️"
        elif any(word in description for word in ("rain", "drizzle", "shower")):
            icon = ""
        elif any(word in description for word in ("wind", "gale", "squall")):
            icon = ""
        elif any(word in description for word in ("heat", "hot")):
            icon = "󰃞"
        elif any(word in description for word in ("fog", "mist", "haze")):
            icon = "🌫️"
        elif "partly" in description or "patchy cloud" in description:
            icon = "🌤️"
        elif any(word in description for word in ("cloud", "overcast")):
            icon = "☁️"
        else:
            icon = ""
        result = {"icon": icon, "temperature": f"{temp}°F", "next_check": now + WEATHER_CACHE_SECONDS}
    except Exception:  # noqa: BLE001
        result = {
            "icon": cached.get("icon", ""),
            "temperature": cached.get("temperature", "Weather unavailable"),
            "next_check": now + WEATHER_RETRY_SECONDS,
        }
    finally:
        try:
            WEATHER_LOCK.unlink()
        except OSError:
            pass

    tmp = WEATHER_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(result))
    os.replace(tmp, WEATHER_CACHE)
    return result["icon"], result["temperature"]


def main():
    now = dt.datetime.now().astimezone()
    try:
        icon, temperature = weather_summary()
    except Exception:
        icon, temperature = "", "Weather unavailable"
    weather = f"{icon}  {temperature}".strip()
    date_weather = f"{now.strftime('%a, %b %-d')} | {weather}"

    clock = clock_lines(now)
    calendar = calendar_lines(now)
    for left, right in zip(clock, calendar):
        print(left_and_right(left, right))
    print(fit_left(date_weather, PANE_WIDTH))


if __name__ == "__main__":
    main()
