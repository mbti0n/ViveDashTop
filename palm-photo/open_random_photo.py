#!/usr/bin/env python3
"""Open the time-appropriate image from ~/Pictures with pinch gestures."""

from __future__ import annotations

import argparse
import math
import os
import signal
import shutil
import subprocess
import threading
import time
from datetime import datetime, time as daytime
from pathlib import Path
from urllib.request import urlopen

import cv2
import mediapipe as mp


PICTURES = Path.home() / "Pictures"
MODEL = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
CAMERA_WINDOW = "Palm photo camera"
PINCH_IN_RATIO = 0.38
PINCH_OUT_RATIO = 0.48
GESTURE_COOLDOWN_SECONDS = 0.75
solar_times_lock = threading.Lock()
solar_times_cache: tuple[daytime, daytime] | None = None
stop_solar_refresh = threading.Event()


def image_files() -> list[Path]:
    return [p for p in PICTURES.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]


def fetch_solar_times() -> tuple[daytime, daytime]:
    """Fetch local sunrise and sunset times from wttr.in."""
    with urlopen("https://wttr.in/?format=%S,%s", timeout=8) as response:
        sunrise_text, sunset_text = response.read().decode("utf-8").strip().split(",", 1)
    return daytime.fromisoformat(sunrise_text), daytime.fromisoformat(sunset_text)


def refresh_solar_times() -> None:
    """Refresh solar data off the camera thread, retrying failures once a minute."""
    global solar_times_cache
    while not stop_solar_refresh.is_set():
        try:
            fetched = fetch_solar_times()
            with solar_times_lock:
                solar_times_cache = fetched
            print("Sunrise/sunset data refreshed from wttr.in")
            retry_after = 6 * 60 * 60
        except Exception as exc:
            print(f"Sunrise/sunset refresh failed; will retry: {exc}")
            retry_after = 60
        stop_solar_refresh.wait(retry_after)


def cached_solar_times() -> tuple[daytime, daytime]:
    with solar_times_lock:
        if solar_times_cache is None:
            raise RuntimeError("Sunrise/sunset data is still loading; try the pinch again shortly")
        return solar_times_cache


def time_period(now: daytime, sunrise: daytime, sunset: daytime) -> str:
    """Map local time to the requested solar/day period."""
    minute = now.hour * 60 + now.minute
    sunrise_minute = sunrise.hour * 60 + sunrise.minute
    sunset_minute = sunset.hour * 60 + sunset.minute

    if minute >= 20 * 60 or minute < sunrise_minute - 30:
        return "evening"
    if minute < sunrise_minute:
        return "before-sunrise"
    if minute < sunrise_minute + 30:
        return "sunrise"
    if minute < 12 * 60:
        return "morning"
    if minute < sunset_minute - 30:
        return "noon"
    if minute < sunset_minute:
        return "before-sunset"
    if minute < sunset_minute + 30:
        return "sunset"
    return "early-evening"


def image_for_period(period: str) -> Path | None:
    return next(
        (p for p in image_files() if p.stem.casefold() == period.casefold()),
        None,
    )


def stop_photo(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def pinch_ratio(hand) -> float:
    """Measure thumb-index fingertip distance relative to palm width."""
    thumb, index = hand[4], hand[8]
    pinky_base, index_base = hand[17], hand[5]
    fingertip_distance = math.hypot(thumb.x - index.x, thumb.y - index.y)
    palm_width = math.hypot(pinky_base.x - index_base.x, pinky_base.y - index_base.y)
    return fingertip_distance / max(palm_width, 1e-6)


def is_neutral_hand(hand) -> bool:
    """Require a visibly open hand before arming pinch recognition."""
    wrist = hand[0]
    extended = 0
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        tip_distance = math.hypot(hand[tip].x - wrist.x, hand[tip].y - wrist.y)
        pip_distance = math.hypot(hand[pip].x - wrist.x, hand[pip].y - wrist.y)
        extended += tip_distance > pip_distance * 1.08
    return extended >= 3


shutdown_requested = False


def request_shutdown(_signal_number, _frame) -> None:
    global shutdown_requested
    shutdown_requested = True
    stop_solar_refresh.set()


def watch_owner(owner_pid: int) -> None:
    """Stop the camera app when the wtfutil process that started it exits."""
    global shutdown_requested
    comm_path = Path(f"/proc/{owner_pid}/comm")
    while not shutdown_requested:
        try:
            owner_name = comm_path.read_text().strip()
        except OSError:
            owner_name = ""
        if owner_name != "wtfutil":
            request_shutdown(signal.SIGTERM, None)
            return
        time.sleep(1)


def main(headless: bool = False, owner_pid: int | None = None) -> None:
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    if owner_pid is not None:
        threading.Thread(
            target=watch_owner,
            args=(owner_pid,),
            name="wtfutil-owner",
            daemon=True,
        ).start()
    if not PICTURES.is_dir() or not image_files():
        raise SystemExit(f"No supported photos found in {PICTURES}")
    if shutil.which("feh") is None:
        raise SystemExit("feh is required to show photos fullscreen. Install it with `sudo apt install feh`.")

    threading.Thread(target=refresh_solar_times, name="solar-times", daemon=True).start()

    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        camera.release()
        video_devices = sorted(Path("/dev").glob("video*"))
        if not video_devices:
            raise SystemExit(
                "No webcam device (/dev/video*) is available. The USB camera is detected, "
                "but its V4L2 driver is not active. Try `sudo modprobe uvcvideo`, then "
                "verify with `v4l2-ctl --list-devices` and run this script again."
            )
        raise SystemExit(
            f"Could not open webcam at index 0 (available devices: {', '.join(map(str, video_devices))}). "
            "Check camera permissions or use the matching camera index."
        )
    # Hand inference may take longer than a camera frame; keep the buffer
    # shallow so gesture checks use recent frames rather than a stale backlog.
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not MODEL.is_file():
        raise SystemExit(f"Hand-tracking model is missing: {MODEL}")

    vision = mp.tasks.vision
    options = vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.55,
        min_hand_presence_confidence=0.55,
        min_tracking_confidence=0.55,
    )
    pinched = False
    gesture_ready = False
    photo_open = False
    quit_owner = False
    photo_process: subprocess.Popen | None = None
    ignore_gestures_until = 0.0
    print("Show an open hand, then pinch to open the image for this time of day fullscreen in feh. Spread to close it. Press Q to quit.")

    try:
        with vision.HandLandmarker.create_from_options(options) as hands:
            if not headless:
                cv2.namedWindow(
                    CAMERA_WINDOW,
                    cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL,
                )
                cv2.resizeWindow(CAMERA_WINDOW, 320, 240)
            status = "Show an open hand to arm pinch recognition"
            while not shutdown_requested:
                ok, frame = camera.read()
                if not ok:
                    print("Could not read from webcam.")
                    break

                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                now = time.monotonic()
                timestamp_ms = time.monotonic_ns() // 1_000_000
                results = hands.detect_for_video(image, timestamp_ms)
                status = "Show an open hand to arm pinch recognition"
                if photo_process is not None and photo_process.poll() is not None:
                    photo_process = None
                    photo_open = False

                if results.hand_landmarks:
                    hand = results.hand_landmarks[0]
                    ratio = pinch_ratio(hand)
                    if now < ignore_gestures_until:
                        # Track the pose without acting, so leaving during cooldown
                        # cannot become a delayed pinch-out when it expires.
                        if ratio <= PINCH_IN_RATIO:
                            pinched = True
                        elif ratio >= PINCH_OUT_RATIO:
                            was_pinched = pinched
                            pinched = False
                            if is_neutral_hand(hand):
                                gesture_ready = True
                            if was_pinched and photo_open:
                                print(
                                    "Pinch-out during cooldown was ignored; after cooldown, pinch in again and spread to close.",
                                    flush=True,
                                )
                        status = f"Gesture cooldown: {ignore_gestures_until - now:.1f}s"
                    elif not gesture_ready:
                        if ratio >= PINCH_OUT_RATIO and is_neutral_hand(hand):
                            gesture_ready = True
                            pinched = False
                            status = "Open hand recognized — pinch thumb and index finger"
                        else:
                            status = "Show an open hand with thumb and index finger apart to arm"
                    elif not pinched and ratio <= PINCH_IN_RATIO:
                        pinched = True
                        if not photo_open:
                            try:
                                sunrise, sunset = cached_solar_times()
                                period = time_period(datetime.now().astimezone().time(), sunrise, sunset)
                                photo = image_for_period(period)
                                if photo is None:
                                    status = f"No image named {period} found in {PICTURES}"
                                else:
                                    photo_process = subprocess.Popen(
                                        ["feh", "--fullscreen", "--auto-zoom", str(photo)],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                    )
                                    photo_open = True
                                    ignore_gestures_until = now + GESTURE_COOLDOWN_SECONDS
                                    print(
                                        f"Opened {photo.name} for {period}; spread after cooldown to close. If you released during cooldown, pinch in again first.",
                                        flush=True,
                                    )
                                    status = f"{period} — fullscreen photo opened"
                            except Exception as exc:
                                print(f"Could not fetch sunrise/sunset or open the photo: {exc}")
                                status = "Could not determine solar time or open photo"
                        else:
                            status = "Pinch in, then spread thumb and index finger to close"
                    elif pinched and ratio >= PINCH_OUT_RATIO:
                        pinched = False
                        if photo_open:
                            stop_photo(photo_process)
                            photo_process = None
                            photo_open = False
                            ignore_gestures_until = now + GESTURE_COOLDOWN_SECONDS
                            print("Pinch-out detected; closing photo", flush=True)
                            status = "Photo closed — pinch to open another"
                        else:
                            status = "Pinch to open a photo"
                    elif photo_open:
                        status = "Pinch in, then spread thumb and index finger to close"
                    else:
                        status = "Bring thumb and index finger together to open a photo"
                elif now < ignore_gestures_until:
                    pinched = False
                    gesture_ready = False
                    status = f"Gesture cooldown: {ignore_gestures_until - now:.1f}s"
                else:
                    pinched = False
                    gesture_ready = False

                if not headless:
                    cv2.imshow(CAMERA_WINDOW, frame)
                    key = cv2.waitKey(1) & 0xFF
                    window_closed = cv2.getWindowProperty(
                        CAMERA_WINDOW, cv2.WND_PROP_VISIBLE
                    ) < 1
                    if key in (ord("q"), 27) or window_closed:
                        quit_owner = owner_pid is not None
                        break
                else:
                    cv2.waitKey(1)
    finally:
        stop_photo(photo_process)
        camera.release()
        cv2.destroyAllWindows()
    if quit_owner and owner_pid is not None:
        try:
            os.kill(owner_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true", help="run gesture detection without showing the webcam preview")
    parser.add_argument("--owner-pid", type=int, help="stop when this wtfutil process exits")
    args = parser.parse_args()
    main(headless=args.headless, owner_pid=args.owner_pid)
