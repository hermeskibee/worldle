"""Letter-by-letter scoring for a WORDLE guess against the target word."""

from collections import Counter

CORRECT = "correct"  # right letter, right position
PRESENT = "present"  # right letter, wrong position
ABSENT = "absent"  # letter not in the word (or no copies left to match)

SYMBOLS = {CORRECT: "\U0001f7e9", PRESENT: "\U0001f7e8", ABSENT: "⬜"}


def score_guess(guess: str, target: str) -> list[str]:
    """Score `guess` against `target`, both 5-letter words.

    Uses the standard two-pass WORDLE algorithm so repeated letters are
    scored against the target's remaining letter counts rather than the
    raw guess: correct-position matches are claimed first, then leftover
    letter copies are handed out to present-but-misplaced matches.
    """
    guess = guess.upper()
    target = target.upper()

    result = [ABSENT] * len(guess)
    remaining = Counter(target)

    for i, letter in enumerate(guess):
        if letter == target[i]:
            result[i] = CORRECT
            remaining[letter] -= 1

    for i, letter in enumerate(guess):
        if result[i] == CORRECT:
            continue
        if remaining[letter] > 0:
            result[i] = PRESENT
            remaining[letter] -= 1

    return result


def render_symbols(scores: list[str]) -> str:
    return " ".join(SYMBOLS[s] for s in scores)
