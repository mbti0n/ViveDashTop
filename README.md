<div align="center">
  <img style="width: 10%" alt="ViveDashTop" src="https://github.com/user-attachments/assets/d84afe59-d0a2-416c-b01f-82b8f44d6ba1" />
  <img style="width: 10%" src="https://xii.swamphacks.com/assets/shxii-icon-transparent-C4fGRz1F.png">
  <h1>ViveDashTop</h2>
  <em>A SwampHacks XII project</em>
  <h4>Old slow laptop, new modern dashboard, build for macOS/Linux<h4>

  <a href="#"><img alt="🌐 Demo" src="https://img.shields.io/badge/%F0%9F%8C%90%20Demo-f59e0b?style=for-the-badge" /></a>
</div>

## The Journey, and The "Why"
*ViveDashTop* was born from an effort to repurpose our old laptops. We had several of them, but they served absolutely no real-world use case for us until we found a mini projector. Through fun experiments with matrix animations, we discovered its potential as a great productivity tool: a smart, minimal dashboard and an aesthetic, surreal "fake" window on your wall.

We expect to make *ViveDashTop* a practical DIY solution for repurposing old laptops, thanks to its extremely lightweight CLI implementation.

## The Challenge
The biggest challenge for *ViveDashTop* was the technical limitations of my mini projector. It has a short power cable and is a low-resolution model. This significantly affected the testing environment for the project. We had to find empty, dark environments to test the projector output. Additionally, we ran into issues when trying to set things up together, mostly regarding API and file permissions.

## Future Plans
- Handle text size and screen resolution better, especially for low-resolution projectors.
- Improve support for macOS.
- Implement gesture detection without requiring an OpenCV window.

## What's Inside?
- A minimal command-line interface (CLI) dashboard optimized for projectors, showing the weather, upcoming events, and sports data.
- An adaptive summary with 3 main points, powered by Google Gemini.
- A "Now Playing" song section, powered by Last.fm.
- **Window Mode**: A screensaver mode that turns the projector dashboard into a fake window in your room. The sky background changes based on the current time. Trigger it by pinching in, and return to the dashboard by pinching out.

## How It Was Built?
- Dashboard base: wtfutil (will become Tessera in the future)
- API Integration: Gemini (API, summary), Last.fm (API, now playing song)
- AI assistant: Codex/GPT 6 Luna, Big Pickle from OpenCode, Cursor
- Hardware: Mini projector, 720p, Surface Laptop Go
- Gesture detection: OpenCV

## How to Use
1. Install wtfutil using Homebrew (macOS/Linux)
```bash
brew install wtfutil
```

2. Copy `config/.env.example` to `config/.env`. Once per project, create an Auth0 Regular Web Application and a Google connection, then put the domain, client id, and client secret in that file.
   - Callback URL: `http://127.0.0.1:8765/callback`
   - Turn on offline access, and turn off refresh token rotation.
   - Enable Connected Accounts for Token Vault on the Google connection.
   - Request `https://www.googleapis.com/auth/calendar.events.readonly`.
   - In Google Cloud, keep the consent screen in testing and add the Gmail addresses that will sign in.

3. Start the dashboard from the repo:
```bash
./config/dashboard.sh
```
The terminal dashboard opens, then a browser window asks you to sign in with Google. Today's calendar shows up after you approve it. The time-of-day photos already live in `Pictures/`.

Gemini and Last.fm stay optional. Add `GEMINI_API_KEY`, `LASTFM_API_KEY`, and `LASTFM_USERNAME` to `config/.env` when you want those filled in.

4. For the palm-photo window, install its libraries into `palm-photo/.venv` from `palm-photo/requirements.txt`.
