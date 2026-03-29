# Campus Chaos

Campus Chaos is a `pygame` campus survival game with live LLM-driven missions, dream phases, rotating maps, and adaptive difficulty.

## What This Repo Includes

- Full game source
- Assets and fonts
- Audio drop folders
- `.env` support for the Groq API key
- A Mac launcher script: [run_game.command](/Users/faleom/Documents/Hackiethon/campus_chaos/run_game.command)
- A Windows launcher script: [run_game_windows.bat](/Users/faleom/Documents/Hackiethon/campus_chaos/run_game_windows.bat)

## Quick Start On Mac

1. Download or clone this repo.
2. Double-click `run_game.command`.

That script will:
- create `.venv` if needed
- install the Python packages from `requirements.txt`
- launch the game

## Quick Start On Windows

1. Download or clone this repo.
2. Double-click `run_game_windows.bat`.

That script will:
- create `.venv` if needed
- install the Python packages from `requirements.txt`
- launch the game

## If macOS Blocks The Launcher

Open Terminal in the project folder and run:

```bash
chmod +x run_game.command
./run_game.command
```

If macOS still complains, especially with messages about moving the file to Trash or blocking it because it was downloaded from the internet, remove the quarantine flag and try again:

```bash
xattr -d com.apple.quarantine run_game.command
chmod +x run_game.command
./run_game.command
```

If the whole project folder is quarantined, use:

```bash
xattr -dr com.apple.quarantine .
chmod +x run_game.command
./run_game.command
```

You can also right-click `run_game.command` and choose `Open` once to bypass Gatekeeper for that file.

## Manual Run

If you want to run it yourself without the launcher:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

On Windows:

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

## LLM Setup

This project expects a Groq API key in `.env`:

```env
GROQ_API_KEY=your_key_here
```

If the key is missing or invalid, the game falls back instead of using the live LLM.

In-game, check the HUD:
- `LLM: LIVE` means the API is being used
- `LLM: OFFLINE` means the built-in fallback is being used instead

## Requirements

- macOS or Windows
- Python 3
- internet connection on first run to install dependencies

Python packages are listed in [requirements.txt](/Users/faleom/Documents/Hackiethon/campus_chaos/requirements.txt):
- `pygame`
- `requests`
- `groq`
- `python-dotenv`

## Audio Setup

The audio system is already wired in. Drop files into:
- [assets/audio/music](/Users/faleom/Documents/Hackiethon/campus_chaos/assets/audio/music)
- [assets/audio/sfx](/Users/faleom/Documents/Hackiethon/campus_chaos/assets/audio/sfx)

See [assets/audio/README.md](/Users/faleom/Documents/Hackiethon/campus_chaos/assets/audio/README.md) for the exact filenames.

## Main Files

- [main.py](/Users/faleom/Documents/Hackiethon/campus_chaos/main.py): main game loop and UI flow
- [settings.py](/Users/faleom/Documents/Hackiethon/campus_chaos/settings.py): screen size and core config
- [game/](/Users/faleom/Documents/Hackiethon/campus_chaos/game): gameplay systems
- [llm/](/Users/faleom/Documents/Hackiethon/campus_chaos/llm): LLM prompts and client logic

## Notes

- This repo currently shares `.env` on purpose for trusted teammates.
- Do not use that pattern for public releases.
- If you change the code, just run `./run_game.command` again.
- On Windows, run `run_game_windows.bat` again after changes.
