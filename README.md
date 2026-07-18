# WORDLE

A terminal WORDLE clone in a single dependency-free Python file, plus a web
version that serves the same game logic through a FastAPI app on Vercel.

## Run it

Requires Python 3.10+, no external packages.

```
python3 wordle.py
```

Add `--random` to skip the word-of-the-day and jump straight into a random word:

```
python3 wordle.py --random
```

## How to play

- Guess the secret 5-letter word in 6 tries.
- After each guess, every letter is marked:
  - 🟩 green — right letter, right position
  - 🟨 yellow — right letter, wrong position
  - ⬜ gray — letter not in the word
- The on-screen keyboard below the board tracks every letter you've used and its
  best known status, so you don't have to re-guess dead letters.
- Guesses must be real 5-letter words; bad input (wrong length, non-letters,
  empty, or not a recognized word) is rejected without costing you an attempt.
- Type `quit` (or `exit` / `:q`) at any prompt to give up on the current game.
  Quitting mid-game never affects your saved stats — only completed games count.

## Modes

- **Daily** (default): everyone gets the same word on a given calendar date, so
  it's comparable day-to-day like the original Wordle.
- **Random** (`--random`, or automatically offered on replay): a fresh random
  word each time, so you can keep playing after finishing the daily one
  without repeating it.

## Stats

Wins, current streak, longest streak, and your guess-count distribution persist
across runs in `~/.wordle_stats.json`.

## Web version

A browser version lives in `api/index.py` — a FastAPI app that reuses the
scoring and word-list logic straight from the bundled `wordle.py` (loaded by
file path, since the root also has a `wordle/` package of the same name).
The game state is kept server-side in memory, keyed by a session cookie.

Routes:

- `GET /` — the terminal-styled HTML/CSS/JS page (dark theme, on-screen
  keyboard, everything inline in the response)
- `POST /api/new` — starts a new game, returns `{"wordLength", "maxAttempts"}`
  and sets the session cookie
- `POST /api/guess` — takes `{"word": "BRAIN"}`, returns
  `{"result", "gameOver", "won", "attempts", "error", "word"}` (`word` is only
  populated once the game is over)

Run it locally with:

```
pip install -r requirements.txt uvicorn
python3 -m uvicorn api.index:app --reload
```

then open `http://127.0.0.1:8000/`.

### Deploying to Vercel

The repo is already set up for it — `vercel.json` configures the Python 3.12
function runtime and `requirements.txt` pins the one dependency (`fastapi`).
From the project root:

```
vercel link      # one-time: link this directory to a Vercel project
vercel dev       # test locally against the real Vercel runtime
vercel deploy    # ship a preview
vercel deploy --prod
```

Note: the in-memory session dict resets whenever Vercel recycles the
serverless instance (cold starts), so long-idle games can lose their state —
fine for a demo, not for anything that needs durable sessions.

## Project layout

```
wordle.py            # bundled, drop-in single-file game (run this)
README.md
vercel.json           # Vercel function config for the web app
requirements.txt       # web app's one dependency (fastapi)
api/
├── __init__.py
└── index.py           # FastAPI app: GET /, POST /api/new, POST /api/guess
wordle/               # modular source used during development
├── wordle.py         # main game loop
├── feedback.py        # letter scoring logic
├── render.py           # ANSI board + keyboard rendering
├── wordlist.py         # curated word list + daily/random selector
├── stats.py            # JSON stats persistence
└── tests/
    └── test_feedback.py
```

`wordle.py` at the project root is self-contained — it's what the modular
`wordle/` package bundles into for distribution, and what `api/index.py`
imports its game logic from. Run the modular version's tests with:

```
cd wordle
python3 -m pytest tests/
```
