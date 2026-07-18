#!/usr/bin/env python3
"""WORDLE — terminal clone. 6 guesses to find the secret 5-letter word."""

import argparse
import sys

import feedback
import render
import stats
import wordlist

MAX_ATTEMPTS = 6
WORD_LENGTH = 5

QUIT_COMMANDS = {"QUIT", ":Q", "EXIT"}


def get_guess(word_length: int) -> str | None:
    """Prompt until a valid guess (or a quit command) is entered.

    Returns the guess in uppercase, or None if the player asked to quit.
    Bad input (wrong length, non-alpha, empty, not a real word) is
    rejected and re-prompted without burning an attempt.
    """
    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            return None

        if not raw:
            print("Type a guess, or 'quit' to give up.")
            continue

        upper = raw.upper()
        if upper in QUIT_COMMANDS:
            return None

        if not upper.isalpha():
            print("Letters only, please.")
            continue

        if len(upper) != word_length:
            print(f"Guesses must be {word_length} letters long.")
            continue

        if not wordlist.is_valid_guess(upper):
            print(f"'{raw}' isn't in the word list.")
            continue

        return upper


def update_letter_status(letter_status: dict[str, str], guess: str, scores: list[str]) -> None:
    priority = {feedback.ABSENT: 0, feedback.PRESENT: 1, feedback.CORRECT: 2}
    for letter, status in zip(guess, scores):
        current = letter_status.get(letter)
        if current is None or priority[status] > priority[current]:
            letter_status[letter] = status


def play_round(target: str, mode: str) -> tuple[bool, int] | None:
    """Play one game against `target`. Returns (won, guesses_used), or None
    if the player quit before the game finished."""
    target = target.upper()
    rows: list[tuple[str, list[str]]] = []
    letter_status: dict[str, str] = {}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(render.render_frame(rows, WORD_LENGTH, MAX_ATTEMPTS, letter_status, attempt, mode))

        guess = get_guess(WORD_LENGTH)
        if guess is None:
            return None

        scores = feedback.score_guess(guess, target)
        rows.append((guess, scores))
        update_letter_status(letter_status, guess, scores)

        if guess == target:
            print(render.render_frame(rows, WORD_LENGTH, MAX_ATTEMPTS, letter_status, attempt, mode))
            print()
            print(render.render_win_banner())
            print(f"\nSolved in {attempt}/{MAX_ATTEMPTS}: {target}\n")
            return True, attempt

    print(render.render_frame(rows, WORD_LENGTH, MAX_ATTEMPTS, letter_status, MAX_ATTEMPTS, mode))
    print(f"\nOut of guesses. The word was: {target}\n")
    return False, MAX_ATTEMPTS


def prompt_yes_no(question: str) -> bool:
    try:
        answer = input(f"{question} (y/n) ").strip().lower()
    except EOFError:
        return False
    return answer.startswith("y")


def run(force_random: bool) -> None:
    print(f"{render.BOLD}{' WORDLE '.center(40, '=')}{render.RESET}")
    print("Guess the 5-letter word in 6 tries. Type 'quit' any time to give up.\n")

    player_stats = stats.load_stats()
    first_game = True

    while True:
        if first_game and not force_random:
            target = wordlist.daily_word()
            mode = "daily"
        else:
            exclude = wordlist.daily_word() if not force_random else None
            target = wordlist.random_word(exclude=exclude)
            mode = "random"
        first_game = False

        result = play_round(target, mode)
        if result is None:
            print("\nThanks for playing — see you next time!")
            break

        won, guesses_used = result
        player_stats = stats.record_game(player_stats, won, guesses_used)
        stats.save_stats(player_stats)
        print(stats.format_stats(player_stats))
        print()

        if not prompt_yes_no("Play again?"):
            print("\nThanks for playing — see you next time!")
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Terminal WORDLE clone.")
    parser.add_argument(
        "--random",
        action="store_true",
        help="skip the word-of-the-day and start with a random word",
    )
    args = parser.parse_args()

    try:
        run(force_random=args.random)
    except KeyboardInterrupt:
        print("\n\nThanks for playing — see you next time!")
        sys.exit(0)


if __name__ == "__main__":
    main()
