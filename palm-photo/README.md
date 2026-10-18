# Palm photo picker

Start with your hand in frame in a neutral open-hand pose (at least three fingers extended, thumb and index finger apart) to arm recognition. Pinch them together to open the image for the current time of day from the repo `Pictures/` folder fullscreen in `feh`. Spread after the 0.75-second cooldown to close it. If you spread during the cooldown, pinch in again first; the initial release is ignored to prevent accidental closure while moving your hand away. Press **Q** or **Esc** in the camera window to quit.

Image filenames should match these periods: `evening`, `before-sunrise`, `sunrise`, `morning`, `noon`, `before-sunset`, `sunset`, and `early-evening` (with any supported image extension). Sunrise and sunset are fetched from [wttr.in](https://wttr.in); the computer's local time is used for the schedule.

## Install

The project includes the hand-tracking model. From this directory, install dependencies into a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python open_random_photo.py
```

The script uses the default webcam (`/dev/video0`) and requires `feh` for fullscreen photos. Allow webcam access if prompted.

## Run with WTFUtil

`config/dashboard.sh` starts the gesture detector with the dashboard. `feh` still needs the active desktop session to display a photo. Check or stop the service with:

```bash
./config/palm-photo-service.sh status
./config/palm-photo-service.sh stop
```

Logs are written to `~/.local/state/palm-photo/gesture.log`.
