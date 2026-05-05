# Overwatch Broadcast Stats Pipeline

A lightweight Python pipeline that reads Overwatch Workshop log files in real time and writes live player stats as structured data files for use in broadcast production tools like vMix, Singular.live, or any system that can consume JSON or plain text files.

---

## How It Works

Overwatch's Workshop mode can output a live log of match data to a local `.txt` file on the host machine. This script watches that directory, parses new lines as they appear, and writes the stats out as either a JSON file or a flat directory of `.txt` files — ready to be consumed by your broadcast tool of choice.

**This only works when:**
- The PC running the script is the **host of the lobby**
- **Workshop Log to File** is enabled in Overwatch settings (see setup below)

---

## Project Files

| File | Description |
|---|---|
| `overwatch_stats_broadcast.py` | Main pipeline script |
| `workshop_code.txt` | Workshop script to paste into Overwatch — copy the full contents and paste into the Workshop code editor in-game |
| `live_stats_example.json` | Example of what the main JSON output looks like at runtime |

---

## Setup

### 1. Enable Workshop Logging in Overwatch

1. Launch Overwatch and open a Custom Game
2. Go to **Settings → Workshop**
3. Set **"Log to File"** to **Enabled**
4. Overwatch will now write log files to:
   ```
   C:\Users\YOUR_USERNAME\Documents\Overwatch\Workshop\
   ```
   Files are named like `Log-YYYY-MM-DD-HH-MM-SS.txt`. The script always picks the most recently modified one.

### 2. Load the Workshop Code

1. In your Custom Game, open **Workshop** → **Edit**
2. Click the **Code** button (top right of the Workshop editor)
3. Paste the full contents of `workshop_code.txt` into the editor
4. Click **OK** and start the game mode

The Workshop script handles emitting the correctly formatted log lines that this pipeline expects.

### 3. Configure the Python Script

Open `overwatch_stats_broadcast.py` and edit the config block near the top:

```python
# Path to the Overwatch Workshop log directory
WORKSHOP_DIR = r"C:\Users\YOUR_USERNAME\Documents\Overwatch\Workshop"

# JSON mode output paths
OUTPUT_JSON        = r"C:\path\to\your\output\live_stats.json"
INDIVIDUAL_JSON_DIR = r"C:\path\to\your\output\Individual Data"

# TXT mode output path
TXT_OUTPUT_DIR = r"C:\path\to\your\output\txt_data"
```

### 4. Choose an Output Mode

At the very top of the script, set the output mode toggle:

```python
OUTPUT_MODE = 0   # 0 = JSON files
OUTPUT_MODE = 1   # 1 = TXT files (flat directory of key/value .txt files)
```

### 5. Run the Script

```bash
python overwatch_stats_broadcast.py
```

Python 3.10 or later is required (uses `dict | None` type hints). No third-party packages are needed — only the standard library.

---

## Output Format

### JSON Mode (`OUTPUT_MODE = 0`)

Two kinds of files are written:

**`live_stats.json`** — a single combined file containing all players, top-level flat keys for every player stat, and a nested `teams` object. This is designed to be pointed at directly as a data source in tools like vMix.

Top-level keys follow the pattern `team_N_player_N_<stat>`, for example:
```
team_1_player_1_name
team_1_player_1_hero
team_1_player_1_eliminations
team_1_player_1_deaths
...
```

See `live_stats_example.json` for a full snapshot of what this looks like with all fields populated.

**`LIVE_team{N}_slot{N}.json`** (written to `INDIVIDUAL_JSON_DIR`) — one file per player slot, per team (10 files total for a 5v5). Each file contains that player's stats plus match context. These are formatted as a single-element object array for compatibility with vMix's data source import.

---

### TXT Mode (`OUTPUT_MODE = 1`)

Instead of JSON, the pipeline writes a flat directory of `.txt` files. Each file is named after a stat key and contains only the value — no formatting, no quotes.

**Main stats** are written directly into `TXT_OUTPUT_DIR`:
```
txt_data/
  updated.txt             → 2025-04-12T14:32:07.841203
  game_mode.txt           → Flashpoint
  map.txt                 → New Junk City
  team_1_name.txt         → Home Team
  team_1_player_1_name.txt  → CoolPlayer1
  team_1_player_1_hero.txt  → Kiriko
  team_1_player_1_eliminations.txt  → 8
  ...
```

**Per-slot stats** are written into subdirectories:
```
txt_data/slot/LIVE_team1_slot0/
  player.txt        → CoolPlayer1
  hero.txt          → Kiriko
  eliminations.txt  → 8
  assists.txt       → 14
  deaths.txt        → 2
  ...
```

This mode is useful for broadcast tools or overlay systems that read individual text files directly, such as certain streaming graphics plugins or lower-third automation workflows.

---

## Stat Fields Reference

| Field | Type | Description |
|---|---|---|
| `player` | string | In-game username |
| `hero` | string | Currently played hero |
| `slot` | int | Workshop player slot (0–4 per team) |
| `match_time` | int | Elapsed match time in seconds |
| `eliminations` | int | Total eliminations |
| `assists` | int | Total assist eliminations |
| `deaths` | int | Total deaths |
| `damage_dealt` | float | Total damage dealt |
| `healing_dealt` | float | Total healing dealt |
| `damage_mitigated` | float | Total damage mitigated (tanks) |
| `weapon_accuracy` | float | Weapon accuracy percentage |
| `critical_hit_accuracy` | float | Critical hit accuracy percentage |
| `final_blows` | float | Final blows (killing shots) |
| `ultimates_used` | int | Number of ultimates used |

---

## Notes

- The script polls every **0.25 seconds** by default. This can be adjusted with `POLL_INTERVAL` in the config.
- Files are written atomically (via a `.tmp` swap) to prevent broadcast tools from reading a half-written file.
- The script only writes a file when its content has actually changed (`WRITE_ONLY_ON_CHANGE = True`), reducing unnecessary disk I/O during static moments.
- If the log file is replaced or truncated (e.g. a new match starts), the script automatically resets and rebuilds state from scratch.
- Heroes that have not yet been selected are skipped by default (`SKIP_EMPTY_HERO = True`).
