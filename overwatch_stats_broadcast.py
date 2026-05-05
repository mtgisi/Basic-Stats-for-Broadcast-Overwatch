import os
import re
import json
import time
import threading
from datetime import datetime

# =========================
# OUTPUT MODE TOGGLE
# =========================
# 0 = JSON mode  — writes a single live_stats.json + per-slot .json files
# 1 = TXT  mode  — writes a flat directory of <key>.txt files (one value per file)
OUTPUT_MODE = 0

# =========================
# CONFIG — edit these values before running
# =========================

# Path to the Overwatch Workshop log directory on this machine
WORKSHOP_DIR = r"C:\Users\YOUR_USERNAME\Documents\Overwatch\Workshop"

# --- JSON mode paths (OUTPUT_MODE = 0) ---
# Path where the combined live stats JSON will be written (e.g. a vMix data source path)
OUTPUT_JSON = r"C:\path\to\your\output\live_stats.json"

# Directory where per-slot JSON files will be written (one file per team/slot combination)
INDIVIDUAL_JSON_DIR = r"C:\path\to\your\output\Individual Data"

# --- TXT mode paths (OUTPUT_MODE = 1) ---
# Directory where flat .txt files will be written (one file per field, named <key>.txt)
# Per-slot data goes into subdirectories: <TXT_OUTPUT_DIR>\slot\LIVE_team1_slot0\<key>.txt
TXT_OUTPUT_DIR = r"C:\path\to\your\output\txt_data"

# =========================
# RUNTIME SETTINGS
# =========================

POLL_INTERVAL = 0.25
SKIP_EMPTY_HERO = True
MIN_LOG_SIZE_BYTES = 1

# Only write when payload changed
WRITE_ONLY_ON_CHANGE = True

# Write compact JSON for speed (JSON mode only)
JSON_DUMP_KWARGS = {
    "ensure_ascii": False,
    "separators": (",", ":")
}

# =========================
# REGEX / GLOBALS
# =========================

timestamp_prefix_re = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")

# Caches so we do not rewrite unchanged content
last_main_json_text = None
last_slot_json_texts = {}
last_main_txt_hash = None
last_slot_txt_hashes = {}

cache_lock = threading.Lock()

# =========================
# HELPERS
# =========================

def safe_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        return float(str(value).strip())
    except Exception:
        return default


def clean_line(line: str) -> str:
    return timestamp_prefix_re.sub("", line.strip())


def json_text(data) -> str:
    return json.dumps(data, **JSON_DUMP_KWARGS, sort_keys=True)


def get_latest_log_file(directory: str):
    try:
        if not os.path.exists(directory):
            return None

        files = [
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.startswith("Log-") and f.endswith(".txt")
        ]

        if not files:
            return None

        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        latest = files[0]

        if os.path.getsize(latest) < MIN_LOG_SIZE_BYTES:
            return None

        return latest

    except Exception as e:
        print("Error finding latest log file:", e)
        return None


def parse_match_meta_line(raw_line: str):
    """
    Expected line:
    [00:00:00] Flashpoint,New Junk City,Illinois State,Bradley,0,0,0,0,0
    """
    line = clean_line(raw_line)

    if not line:
        return None
    if line.startswith(","):
        return None
    if line.startswith("-----"):
        return None
    if line.startswith("live,") or line.startswith("hero_") or line.startswith("summary,") or line.startswith("roster,"):
        return None

    parts = [p.strip() for p in line.split(",")]

    if len(parts) < 4:
        return None

    game_mode  = parts[0]
    map_name   = parts[1]
    team_1_name = parts[2]
    team_2_name = parts[3]

    if not game_mode or not map_name:
        return None

    return {
        "game_mode":   game_mode,
        "map":         map_name,
        "team_1_name": team_1_name,
        "team_2_name": team_2_name,
    }


def parse_live_line(raw_line: str):
    """
    Expected line:
    [00:00:00] ,live,0,4,Illinois State,PlayerName,Brigitte,0,0,0,0,0,0,0,0,0,0

    Indexes:
      0  = ""
      1  = "live"
      2  = match_time
      3  = slot
      4  = team
      5  = player
      6  = hero
      7  = eliminations
      8  = assists
      9  = deaths
      10 = damage_dealt
      11 = healing_dealt
      12 = damage_mitigated
      13 = weapon_accuracy
      14 = critical_hit_accuracy
      15 = final_blows
      16 = ultimates_used
    """
    line = clean_line(raw_line)

    if not line.startswith(",live,"):
        return None

    parts = line.split(",")

    if len(parts) < 17:
        return None

    slot   = safe_int(parts[3])
    team   = parts[4].strip()
    player = parts[5].strip()
    hero   = parts[6].strip()

    if not team:
        return None
    if SKIP_EMPTY_HERO and hero == "":
        return None

    return {
        "match_time":            safe_int(parts[2]),
        "slot":                  slot,
        "team":                  team,
        "player":                player,
        "hero":                  hero,
        "eliminations":          safe_int(parts[7]),
        "assists":               safe_int(parts[8]),
        "deaths":                safe_int(parts[9]),
        "damage_dealt":          safe_float(parts[10]),
        "healing_dealt":         safe_float(parts[11]),
        "damage_mitigated":      safe_float(parts[12]),
        "weapon_accuracy":       safe_float(parts[13]),
        "critical_hit_accuracy": safe_float(parts[14]),
        "final_blows":           safe_int(parts[15]),
        "ultimates_used":        safe_int(parts[16]),
    }


# =========================
# JSON BUILDING
# =========================

def build_main_json(players_by_key: dict, match_meta: dict | None = None, source_file: str = ""):
    """Build the combined broadcast JSON payload (all players, flat top-level keys)."""
    players = list(players_by_key.values())

    team_names = []
    if match_meta:
        if match_meta.get("team_1_name"):
            team_names.append(match_meta["team_1_name"])
        if match_meta.get("team_2_name") and match_meta["team_2_name"] not in team_names:
            team_names.append(match_meta["team_2_name"])

    for p in players:
        if p["team"] not in team_names:
            team_names.append(p["team"])

    teams = {team: [] for team in team_names}
    for p in players:
        teams.setdefault(p["team"], []).append(p)
    for team in teams:
        teams[team] = sorted(teams[team], key=lambda x: x["slot"])

    output = {
        "updated":     datetime.now().isoformat(),
        "source_file": source_file,
        "game_mode":   match_meta.get("game_mode", "") if match_meta else "",
        "map":         match_meta.get("map", "") if match_meta else "",
        "team_1_name": team_names[0] if len(team_names) > 0 else "",
        "team_2_name": team_names[1] if len(team_names) > 1 else "",
        "teams":       {},
        "players":     players,
    }

    for team_index, team_name in enumerate(team_names, start=1):
        team_players = teams.get(team_name, [])
        output["teams"][team_name] = team_players

        for player_index, p in enumerate(team_players, start=1):
            prefix = f"team_{team_index}_player_{player_index}"

            output[f"{prefix}_slot"]                  = p["slot"]
            output[f"{prefix}_name"]                  = p["player"]
            output[f"{prefix}_hero"]                  = p["hero"]
            output[f"{prefix}_team"]                  = p["team"]
            output[f"{prefix}_match_time"]            = p["match_time"]
            output[f"{prefix}_eliminations"]          = p["eliminations"]
            output[f"{prefix}_assists"]               = p["assists"]
            output[f"{prefix}_deaths"]                = p["deaths"]
            output[f"{prefix}_damage_dealt"]          = p["damage_dealt"]
            output[f"{prefix}_healing_dealt"]         = p["healing_dealt"]
            output[f"{prefix}_damage_mitigated"]      = p["damage_mitigated"]
            output[f"{prefix}_weapon_accuracy"]       = p["weapon_accuracy"]
            output[f"{prefix}_critical_hit_accuracy"] = p["critical_hit_accuracy"]
            output[f"{prefix}_final_blows"]           = p["final_blows"]
            output[f"{prefix}_ultimates_used"]        = p["ultimates_used"]

    return output


def build_slot_payloads(players_by_key: dict, match_meta: dict | None = None, source_file: str = ""):
    """Build per-slot broadcast payloads. Returns list of (file_path, data) tuples."""
    team_1_name = match_meta.get("team_1_name", "") if match_meta else ""
    team_2_name = match_meta.get("team_2_name", "") if match_meta else ""

    team_lookup = {1: team_1_name, 2: team_2_name}

    players_lookup = {}
    for player_data in players_by_key.values():
        team = player_data.get("team", "")
        slot = safe_int(player_data.get("slot", -1))
        players_lookup[(team, slot)] = player_data

    slot_payloads = []

    for team_index in [1, 2]:
        team_name = team_lookup.get(team_index, "")

        for slot in range(0, 5):
            player_data = players_lookup.get((team_name, slot))

            row = {
                "updated":     datetime.now().isoformat(),
                "source_file": source_file,
                "game_mode":   match_meta.get("game_mode", "") if match_meta else "",
                "map":         match_meta.get("map", "") if match_meta else "",
                "team_1_name": team_1_name,
                "team_2_name": team_2_name,
                "team_index":  team_index,
                "team":        team_name,
                "slot":        slot,
                "has_data":    player_data is not None,
            }

            if player_data:
                row.update({
                    "match_time":            player_data.get("match_time", 0),
                    "player":                player_data.get("player", ""),
                    "hero":                  player_data.get("hero", ""),
                    "eliminations":          player_data.get("eliminations", 0),
                    "assists":               player_data.get("assists", 0),
                    "deaths":                player_data.get("deaths", 0),
                    "damage_dealt":          player_data.get("damage_dealt", 0.0),
                    "healing_dealt":         player_data.get("healing_dealt", 0.0),
                    "damage_mitigated":      player_data.get("damage_mitigated", 0.0),
                    "weapon_accuracy":       player_data.get("weapon_accuracy", 0.0),
                    "critical_hit_accuracy": player_data.get("critical_hit_accuracy", 0.0),
                    "final_blows":           player_data.get("final_blows", 0),
                    "ultimates_used":        player_data.get("ultimates_used", 0),
                })
            else:
                row.update({
                    "match_time":            0,
                    "player":                "",
                    "hero":                  "",
                    "eliminations":          0,
                    "assists":               0,
                    "deaths":                0,
                    "damage_dealt":          0.0,
                    "healing_dealt":         0.0,
                    "damage_mitigated":      0.0,
                    "weapon_accuracy":       0.0,
                    "critical_hit_accuracy": 0.0,
                    "final_blows":           0,
                    "ultimates_used":        0,
                })

            file_stem = f"LIVE_team{team_index}_slot{slot}"
            slot_payloads.append((file_stem, row))

    return slot_payloads


# =========================
# FILE I/O — JSON MODE
# =========================

def write_text_atomic(path: str, text: str):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def write_json_if_changed(path: str, data, cache_key: str, cache_dict: dict):
    payload = json_text(data)
    with cache_lock:
        if cache_dict.get(cache_key) == payload:
            return False
        cache_dict[cache_key] = payload
    write_text_atomic(path, payload)
    return True


# =========================
# FILE I/O — TXT MODE
# =========================

def flatten_for_txt(data: dict) -> dict[str, str]:
    """
    Flatten a payload dict into {key: str_value} pairs suitable for .txt output.
    Complex values (lists, dicts) are JSON-serialised into their txt file.
    """
    result = {}
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            result[k] = json.dumps(v, **JSON_DUMP_KWARGS, sort_keys=True)
        else:
            result[k] = str(v)
    return result


def write_txt_dir(directory: str, flat: dict[str, str]):
    """Write each key/value pair as <directory>/<key>.txt atomically."""
    os.makedirs(directory, exist_ok=True)
    for key, value in flat.items():
        path = os.path.join(directory, f"{key}.txt")
        write_text_atomic(path, value)


def txt_hash(flat: dict[str, str]) -> str:
    """Cheap change-detection hash for a flat txt payload."""
    return json_text(flat)


def write_txt_if_changed(directory: str, flat: dict[str, str], cache_key: str, cache_dict: dict) -> bool:
    h = txt_hash(flat)
    with cache_lock:
        if cache_dict.get(cache_key) == h:
            return False
        cache_dict[cache_key] = h
    write_txt_dir(directory, flat)
    return True


# =========================
# CACHE RESET
# =========================

def reset_caches_for_new_match():
    global last_main_json_text, last_slot_json_texts
    global last_main_txt_hash, last_slot_txt_hashes
    with cache_lock:
        last_main_json_text   = None
        last_slot_json_texts  = {}
        last_main_txt_hash    = None
        last_slot_txt_hashes  = {}


# =========================
# MAIN LOOP
# =========================

def main():
    mode_label = "JSON" if OUTPUT_MODE == 0 else "TXT"
    print(f"Output mode:       {mode_label}")
    print(f"Watching dir:      {WORKSHOP_DIR}")

    if OUTPUT_MODE == 0:
        print(f"Main JSON output:  {OUTPUT_JSON}")
        print(f"Slot JSON dir:     {INDIVIDUAL_JSON_DIR}")
    else:
        print(f"TXT output dir:    {TXT_OUTPUT_DIR}")

    print(f"Poll interval:     {POLL_INTERVAL:.2f}s")

    current_input_txt = None
    players_by_key    = {}
    match_meta        = {}
    file_position     = 0
    last_seen_size    = 0

    while True:
        loop_started = time.perf_counter()

        try:
            latest_file = get_latest_log_file(WORKSHOP_DIR)

            if not latest_file:
                print("No log files found.")
                elapsed = time.perf_counter() - loop_started
                time.sleep(max(0, POLL_INTERVAL - elapsed))
                continue

            # New log file detected — reset all state
            if latest_file != current_input_txt:
                current_input_txt = latest_file
                file_position     = 0
                last_seen_size    = 0
                players_by_key    = {}
                match_meta        = {}
                reset_caches_for_new_match()
                print(f"Switched to new log file: {current_input_txt}")

            if not os.path.exists(current_input_txt):
                print("Current input file not found.")
                elapsed = time.perf_counter() - loop_started
                time.sleep(max(0, POLL_INTERVAL - elapsed))
                continue

            current_size = os.path.getsize(current_input_txt)

            # File was truncated/reset
            if current_size < file_position:
                file_position  = 0
                last_seen_size = 0
                players_by_key = {}
                match_meta     = {}
                reset_caches_for_new_match()
                print("Input file was truncated/reset. Rebuilding state.")

            # Fast path: nothing new
            if current_size == file_position and current_size == last_seen_size:
                elapsed = time.perf_counter() - loop_started
                time.sleep(max(0, POLL_INTERVAL - elapsed))
                continue

            last_seen_size = current_size

            with open(current_input_txt, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(file_position)
                new_lines     = f.readlines()
                file_position = f.tell()

            changed = False

            for raw_line in new_lines:
                meta = parse_match_meta_line(raw_line)
                if meta:
                    if meta != match_meta:
                        match_meta = meta
                        changed    = True
                    continue

                parsed = parse_live_line(raw_line)
                if not parsed:
                    continue

                key      = f"{parsed['team']}::{parsed['slot']}"
                previous = players_by_key.get(key)

                if previous != parsed:
                    players_by_key[key] = parsed
                    changed             = True

            if not (changed or (players_by_key and last_main_json_text is None)):
                elapsed = time.perf_counter() - loop_started
                time.sleep(max(0, POLL_INTERVAL - elapsed))
                continue

            main_payload  = build_main_json(players_by_key, match_meta, current_input_txt)
            slot_payloads = build_slot_payloads(players_by_key, match_meta, current_input_txt)

            main_written      = False
            slot_write_count  = 0

            # ------ JSON MODE ------
            if OUTPUT_MODE == 0:
                main_written = write_json_if_changed(
                    path      = OUTPUT_JSON,
                    data      = main_payload,
                    cache_key = OUTPUT_JSON,
                    cache_dict= last_slot_json_texts,  # reuse dict; key is unique
                )

                for file_stem, slot_data in slot_payloads:
                    file_path = os.path.join(INDIVIDUAL_JSON_DIR, f"{file_stem}.json")
                    if write_json_if_changed(
                        path       = file_path,
                        data       = [slot_data],   # vMix expects object-array format
                        cache_key  = file_path,
                        cache_dict = last_slot_json_texts,
                    ):
                        slot_write_count += 1

            # ------ TXT MODE ------
            else:
                main_flat = flatten_for_txt(main_payload)
                main_written = write_txt_if_changed(
                    directory  = TXT_OUTPUT_DIR,
                    flat       = main_flat,
                    cache_key  = "__main__",
                    cache_dict = last_slot_txt_hashes,
                )

                for file_stem, slot_data in slot_payloads:
                    slot_dir  = os.path.join(TXT_OUTPUT_DIR, "slot", file_stem)
                    slot_flat = flatten_for_txt(slot_data)
                    if write_txt_if_changed(
                        directory  = slot_dir,
                        flat       = slot_flat,
                        cache_key  = file_stem,
                        cache_dict = last_slot_txt_hashes,
                    ):
                        slot_write_count += 1

            print(
                f"Updated {len(players_by_key)} players | "
                f"main_written={main_written} | "
                f"slot_files_written={slot_write_count} | "
                f"mode={main_payload.get('game_mode', '')} | "
                f"map={main_payload.get('map', '')} | "
                f"team1={main_payload.get('team_1_name', '')} | "
                f"team2={main_payload.get('team_2_name', '')}"
            )

        except Exception as e:
            print("Error:", e)

        elapsed = time.perf_counter() - loop_started
        time.sleep(max(0, POLL_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
