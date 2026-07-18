import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feedback import CORRECT, PRESENT, ABSENT, score_guess


def test_all_correct():
    assert score_guess("BRAIN", "BRAIN") == [CORRECT] * 5


def test_all_wrong():
    # target "BRAIN" has none of these letters
    assert score_guess("TOUCH", "BRAIN") == [ABSENT] * 5


def test_mixed():
    # target CRATE, guess TRACE
    # T: in CRATE at index 3, guessed at 0 -> present
    # R: correct position (1)
    # A: in CRATE at index 2, guessed at 2 -> correct
    # C: in CRATE at index 0, guessed at 3 -> present
    # E: correct position (4)
    assert score_guess("TRACE", "CRATE") == [
        PRESENT,
        CORRECT,
        CORRECT,
        PRESENT,
        CORRECT,
    ]


def test_duplicate_letter_in_guess_single_in_target():
    # target has one "L", guess has two "L"s.
    # SPELL vs. target LEMON: only one L in target, at index 0.
    # guess: S P E L L
    # S absent, P absent, E present (LEMON has E at idx1), first L present
    # (matches remaining L), second L absent (no more L left to match)
    assert score_guess("SPELL", "LEMON") == [
        ABSENT,
        ABSENT,
        PRESENT,
        PRESENT,
        ABSENT,
    ]


def test_duplicate_letter_correct_position_consumes_before_present():
    # target ALLOW, guess LLAMA
    # target letters: A L L O W  (indices 0-4)
    # guess:          L L A M A
    # idx0 L: target[0]=A -> not a positional match
    # idx1 L: target[1]=L -> correct
    # idx2 A: target[2]=L -> not a positional match
    # idx3 M: not in target -> absent
    # idx4 A: target[4]=W -> not a positional match
    #
    # First pass claims idx1 as CORRECT, leaving one L and one A in the pool.
    # Second pass: idx0 L draws the remaining L (present), idx2 A draws the
    # remaining A (present), idx4 A finds the pool empty (absent).
    assert score_guess("LLAMA", "ALLOW") == [
        PRESENT,
        CORRECT,
        PRESENT,
        ABSENT,
        ABSENT,
    ]


def test_duplicate_letter_in_target_single_in_guess():
    # target MOMMY has three Ms, guess has one M which is in the right spot
    assert score_guess("MADLY", "MOMMY") == [
        CORRECT,
        ABSENT,
        ABSENT,
        ABSENT,
        CORRECT,
    ]


def test_case_insensitive():
    assert score_guess("brain", "BRAIN") == [CORRECT] * 5
    assert score_guess("Brain", "brain") == [CORRECT] * 5


def test_win_on_final_attempt_scoring_is_still_correct():
    # not attempt-tracking, just confirms scoring works identically regardless
    # of which guess number it is
    assert score_guess("CRANE", "CRANE") == [CORRECT] * 5
