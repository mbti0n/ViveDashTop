<div align="center">
  <img style="width: 10%" alt="ViveDashTop" src="https://github.com/user-attachments/assets/d84afe59-d0a2-416c-b01f-82b8f44d6ba1" />
  <img style="width: 10%" src="https://xii.swamphacks.com/assets/shxii-icon-transparent-C4fGRz1F.png">
  <h1>ViveDashTop</h2>
  <em>A SwampHacks XII project</em>
  <h4>Old slow laptop, new modern dashboard, build for macOS/Linux<h4>

  <a href="#"><img alt="🌐 Demo" src="https://img.shields.io/badge/%F0%9F%8C%90%20Demo-f59e0b?style=for-the-badge" /></a>
</div>

## The Journey, and The "Why"
*ViveDashTop* came into life during my effort of repurposing old laptops. I have several of them sitting around my bedroom, and I could not stop thinking of their real use case. Decentralizing a laptop could be fine because it could ease the pressure for my main machine, but I find that complicated. There are days that I completely ignore my spare laptops, increasing the weight of my backpack for nothing. I recenetly got a new mini projector, then eventually I tested it with one of my laptop. 

## The Challenge
The biggest challenge to *ViveDashTop* was the technical limitation of my mini projector. It has a short power cable, and it is a low-resolution model. This significantly affected testing environment

## Future Plan


## What's In It?



## How It Was Built?
- Dashboard base: wtfutil (will become tessera in the future)
- API Integration: Gemini (API, summary), Last.fm (API, now playing song)
- AI assistant: Codex/GPT 6 Luna and Big Pickle from OpenCode
- Hardware: mini projector, 720p
- Gesture detection: OpenCV

## How to Use
1. Install wtfutil using Homebrew (macOS/Linux)
```bash
brew install wtfutil
```

2. Install gcalcli using Homebrew (macOS/Linux)
```bash
brew install gcalcli
```

3. Run `gcalcli init` to setup the Google Calendar API. Access the Google Calendar API from Google Cloud console.

4. Copy all files inside the `config` folder into `~/.config/wtf/`. Remember to rename the `.env.example` file to `.env` then specify Gemini API Key, Last.fm API key, and Last.fm account name.
5. Copy all images inside the `Pictures` folder into `~/Pictures`
