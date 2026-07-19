# ✅ WORDLE — QA Spec (Playwright)

> Test suite: `scripts/qa-test.mjs` (37 tests)
> Base URL: `http://127.0.0.1:8811` (local) or `https://wordle.mindster.space` (production)

---

## Critical tests (must pass)

### 1. Page load
- [x] `GET /` → 200
- [x] Title "WORDLE" visible
- [x] Footer "Created by Mindster · Moca Mind" visible (hidden below the 700px height breakpoint on small phones)
- [x] 5×6 tile grid visible, no tile overlap even on 320×568
- [x] On-screen keyboard visible (26 letters + ENTER + DEL = 28 keys)
- [x] No console/page errors, no horizontal overflow

### 2. Gameplay
- [x] `POST /api/new` → 200, sets signed `wordle_state` cookie, resets attempts to 0/6
- [x] `POST /api/guess` → 200, returns per-letter result (`correct` / `present` / `absent`)
- [x] Correct-position letters and duplicate letters scored per standard Wordle rules
- [x] Win: all 5 letters correct → "Solved in X/6" message, sparkle particles, timer freezes
- [x] Loss: 6 wrong guesses → "Out of guesses" message, reveals the target word, timer freezes
- [x] Guess not in the word list → "isn't in the word list" message, attempt NOT consumed
- [x] Guess shorter than 5 letters → "Not enough letters" message, attempt NOT consumed
- [x] New Game after a win or a loss resets tiles/message/attempts and starts a fresh target
- [x] Rapid double-click on New Game, and double-tap ENTER on the winning guess, do not double-submit or corrupt state
- [x] A dropped `/api/guess` network request shows a retry message, doesn't consume an attempt, and doesn't soft-lock the game

### 3. Hints (`POST /api/hint`, three levels, penalty stacks in seconds on the timer)
- [x] Level 1 (+15s): reveals one random correct letter as a `.tile.hinted`; already-revealed/green positions are never re-picked
- [x] Level 2 (+30s): shows up to 5 sample candidate words matching guesses so far
- [x] Level 3 (+60s): lists all remaining candidate words (target is always among them)
- [x] Hint modal never breaks layout (no horizontal overflow, modal fits inside viewport)
- [x] Word chips (level 2/3) are clickable and submit that word as a guess

Note: there is no "pin hint" checkbox in the current implementation.

### 4. Keyboard & UI
- [x] Clicking a letter key types it into the active row
- [x] Letters ruled out (`absent`) become disabled/unclickable on the on-screen keyboard
- [x] All keys (letters, ENTER, DEL) become disabled once the game is over
- [x] DEL removes the last entered letter
- [x] Typing a 6th letter before submitting is ignored (`currentGuess` stays at 5 chars)
- [x] Double-tap on the keyboard/board does not trigger browser zoom (`touch-action: manipulation` everywhere, plus `maximum-scale=1`/`user-scalable=no` on the viewport meta)

### 5. Timer
- [x] Timer starts at `00:00` and counts **up** (not down) during play
- [x] Hint penalties add seconds directly to the displayed timer
- [x] Timer freezes on win and on loss

Note: there is no countdown-to-zero / time's-up game-over mode in the current implementation.

### 6. Mobile & layout
- [x] No horizontal overflow at 320×568, 375×667, 390×844, 430×932, 1440×900
- [x] No vertical overflow / internal scroll traps at 320×568 through 412×914 (iPhone SE → Pixel 7 Pro)
- [x] Board and keyboard stay fully visible and non-overlapping at every tested size
- [x] Content is vertically centered on tall phones (no dead space stranded at the bottom)
- [x] `html`/`body` background matches the page theme (no white flash/gap)

### 7. Daily mode

Not implemented. There is no `/api/daily` endpoint, no shared daily word, and no streak/stats tracking — every `POST /api/new` deals an independent random target from the word list. If daily mode is wanted, it needs to be scoped and built; this spec will be updated once it exists.

---

## Running

```bash
# Local (start the server first)
cd ~/projects/mocaminds/worldle
python3 -m api.index  # or however it's run locally
node scripts/qa-test.mjs

# Against production
QA_BASE_URL=https://wordle.mindster.space node scripts/qa-test.mjs
```

## QA loop rule

> **After EVERY code change → run the Playwright QA suite.**
> If even one test fails → do NOT push.
> Fix and loop (`node scripts/qa-test.mjs`) until everything passes.
> Only then commit + push + report.
