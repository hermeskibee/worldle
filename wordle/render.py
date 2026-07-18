"""ANSI board and keyboard rendering for the terminal WORDLE UI."""

from feedback import ABSENT, CORRECT, PRESENT

RESET = "\033[0m"
BOLD = "\033[1m"

_TILE_COLORS = {
    CORRECT: "\033[1;97;42m",  # white text, green background
    PRESENT: "\033[1;97;43m",  # white text, yellow background
    ABSENT: "\033[1;97;100m",  # white text, gray background
}
_UNUSED_KEY = "\033[90m"  # dim gray, letter not guessed yet

QWERTY_ROWS = ("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")

WIN_BANNER = r"""
 __     ______  _    _  __          _______ _   _ _
 \ \   / / __ \| |  | | \ \        / /_   _| \ | | |
  \ \_/ / |  | | |  | |  \ \  /\  / /  | | |  \| | |
   \   /| |  | | |  | |   \ \/  \/ /   | | | . ` | |
    | | | |__| | |__| |    \  /\  /   _| |_| |\  |_|
    |_|  \____/ \____/      \/  \/   |_____|_| \_(_)
""".strip("\n")


def clear_screen() -> str:
    return "\033[2J\033[H"


def render_tile(letter: str, status: str | None) -> str:
    if status is None:
        return f" {letter} "
    color = _TILE_COLORS[status]
    return f"{color} {letter} {RESET}"


def render_board(rows: list[tuple[str, list[str]]], word_length: int, max_attempts: int) -> str:
    lines = []
    for guess, scores in rows:
        tiles = "".join(render_tile(letter, status) for letter, status in zip(guess, scores))
        lines.append(tiles)
    for _ in range(max_attempts - len(rows)):
        lines.append("".join(render_tile(" ", None) for _ in range(word_length)))
    return "\n".join(lines)


def render_keyboard(letter_status: dict[str, str]) -> str:
    lines = []
    for row in QWERTY_ROWS:
        keys = []
        for letter in row:
            status = letter_status.get(letter)
            if status is None:
                keys.append(f"{_UNUSED_KEY}{letter}{RESET}")
            else:
                color = _TILE_COLORS[status]
                keys.append(f"{color}{letter}{RESET}")
        lines.append(" ".join(keys))
    return "\n".join(lines)


def render_header(attempt: int, max_attempts: int, mode: str) -> str:
    title = f" WORDLE · {mode} · attempt {attempt}/{max_attempts} "
    return f"{BOLD}{title.center(40, '=')}{RESET}"


def render_frame(rows, word_length, max_attempts, letter_status, attempt, mode) -> str:
    parts = [
        render_header(attempt, max_attempts, mode),
        "",
        render_board(rows, word_length, max_attempts),
        "",
        "Keyboard:",
        render_keyboard(letter_status),
        "",
    ]
    return "\n".join(parts)


def render_win_banner() -> str:
    return f"\033[1;92m{WIN_BANNER}\033[0m"
