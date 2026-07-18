"""Cross-game stats persistence (wins, streak, guess distribution)."""

import json
from pathlib import Path

DEFAULT_STATS_PATH = Path.home() / ".wordle_stats.json"

DEFAULT_STATS = {
    "games_played": 0,
    "wins": 0,
    "current_streak": 0,
    "max_streak": 0,
    # keys "1".."6": how many wins took that many guesses
    "guess_distribution": {str(n): 0 for n in range(1, 7)},
}


def load_stats(path: Path = DEFAULT_STATS_PATH) -> dict:
    """Load stats from disk, falling back to fresh defaults if the file is
    missing or corrupt so a bad/partial write never crashes the game."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_STATS, guess_distribution=dict(DEFAULT_STATS["guess_distribution"]))

    stats = dict(DEFAULT_STATS, guess_distribution=dict(DEFAULT_STATS["guess_distribution"]))
    stats.update({k: v for k, v in data.items() if k in DEFAULT_STATS})
    if isinstance(data.get("guess_distribution"), dict):
        stats["guess_distribution"].update(data["guess_distribution"])
    return stats


def save_stats(stats: dict, path: Path = DEFAULT_STATS_PATH) -> None:
    # Write to a temp file then rename, so a crash mid-write can't corrupt
    # the previous, still-valid stats file.
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(stats, f, indent=2)
    tmp_path.replace(path)


def record_game(stats: dict, won: bool, guesses_used: int) -> dict:
    """Update stats for one *completed* game. Only call this once a game has
    actually ended (win or loss) -- an aborted/quit game must never call
    this, so mid-game quits never corrupt the running stats."""
    stats = dict(stats, guess_distribution=dict(stats["guess_distribution"]))
    stats["games_played"] += 1

    if won:
        stats["wins"] += 1
        stats["current_streak"] += 1
        stats["max_streak"] = max(stats["max_streak"], stats["current_streak"])
        key = str(guesses_used)
        stats["guess_distribution"][key] = stats["guess_distribution"].get(key, 0) + 1
    else:
        stats["current_streak"] = 0

    return stats


def format_stats(stats: dict) -> str:
    played = stats["games_played"]
    wins = stats["wins"]
    win_pct = round(100 * wins / played) if played else 0

    lines = [
        "Stats:",
        f"  Played: {played}   Win %: {win_pct}   "
        f"Current streak: {stats['current_streak']}   Max streak: {stats['max_streak']}",
        "  Guess distribution:",
    ]
    max_count = max(stats["guess_distribution"].values(), default=0)
    for n in range(1, 7):
        count = stats["guess_distribution"].get(str(n), 0)
        bar_len = round(20 * count / max_count) if max_count else 0
        bar = "#" * bar_len or ("" if count == 0 else "#")
        lines.append(f"    {n}: {bar} {count}")
    return "\n".join(lines)
