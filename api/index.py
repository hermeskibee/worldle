import importlib.util
import secrets
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# wordle.py and the wordle/ package share the name "wordle" at the project
# root, so `import wordle` is ambiguous. Load the bundled file directly by
# path under a distinct module name to sidestep that collision.
_BUNDLE_PATH = Path(__file__).resolve().parent.parent / "wordle.py"
_spec = importlib.util.spec_from_file_location("wordle_bundled", _BUNDLE_PATH)
wordle_bundled = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wordle_bundled)

score_guess = wordle_bundled.score_guess
is_valid_guess = wordle_bundled.is_valid_guess
random_word = wordle_bundled.random_word
MAX_ATTEMPTS = wordle_bundled.MAX_ATTEMPTS
WORD_LENGTH = wordle_bundled.WORD_LENGTH

app = FastAPI()

COOKIE_NAME = "wordle_sid"

# Serverless instances can be recycled between requests, which silently
# resets this dict — fine for a demo, but games aren't guaranteed to survive
# across cold starts.
GAMES: dict[str, dict] = {}


class GuessRequest(BaseModel):
    word: str


def _start_game() -> tuple[str, dict]:
    session_id = secrets.token_hex(16)
    game = {"target": random_word(), "attempts": [], "game_over": False, "won": False}
    GAMES[session_id] = game
    return session_id, game


def _get_or_create_game(request: Request) -> tuple[str, dict, bool]:
    session_id = request.cookies.get(COOKIE_NAME)
    game = GAMES.get(session_id) if session_id else None
    if game is not None:
        return session_id, game, False
    session_id, game = _start_game()
    return session_id, game, True


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,
    )


@app.post("/api/new")
def new_game() -> JSONResponse:
    session_id, _game = _start_game()
    response = JSONResponse({"wordLength": WORD_LENGTH, "maxAttempts": MAX_ATTEMPTS})
    _set_session_cookie(response, session_id)
    return response


@app.post("/api/guess")
def guess(payload: GuessRequest, request: Request) -> JSONResponse:
    session_id, game, is_new = _get_or_create_game(request)
    word = payload.word.strip().upper()

    def respond(**extra) -> JSONResponse:
        body = {
            "result": None,
            "gameOver": game["game_over"],
            "won": game["won"],
            "attempts": game["attempts"],
            "error": None,
            "word": game["target"] if game["game_over"] else None,
        }
        body.update(extra)
        response = JSONResponse(body)
        if is_new:
            _set_session_cookie(response, session_id)
        return response

    if game["game_over"]:
        return respond(error="Game is already over. Start a new game.")

    if len(word) != WORD_LENGTH or not word.isalpha():
        return respond(error=f"Guess must be a {WORD_LENGTH}-letter word.")

    if not is_valid_guess(word):
        return respond(error=f"'{word}' isn't in the word list.")

    result = score_guess(word, game["target"])
    game["attempts"].append({"word": word, "result": result})

    won = word == game["target"]
    out_of_attempts = len(game["attempts"]) >= MAX_ATTEMPTS
    if won or out_of_attempts:
        game["game_over"] = True
        game["won"] = won

    return respond(result=result)


HTML_PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>WORDLE</title>
<style>
  :root {
    --bg: #1a1a2e;
    --panel: #16213e;
    --fg: #39ff14;
    --amber: #ffb000;
    --dim: #4a4a6a;
    --correct: #2e7d32;
    --present: #b8860b;
    --absent: #333344;
  }
  * { box-sizing: border-box; }
  html, body {
    height: 100%;
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font-family: "Courier New", Courier, monospace;
  }
  body {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px 12px 40px;
  }
  h1 {
    color: var(--amber);
    letter-spacing: 0.5em;
    text-shadow: 0 0 8px rgba(255, 176, 0, 0.5);
    margin: 8px 0 4px;
    font-size: 1.8rem;
  }
  .subtitle {
    color: var(--dim);
    margin-bottom: 20px;
    font-size: 0.85rem;
  }
  .terminal {
    width: 100%;
    max-width: 420px;
    background: var(--panel);
    border: 1px solid var(--dim);
    border-radius: 6px;
    box-shadow: 0 0 24px rgba(57, 255, 20, 0.08);
    padding: 20px;
  }
  #board {
    display: grid;
    grid-template-rows: repeat(6, 1fr);
    gap: 6px;
    margin-bottom: 18px;
  }
  .row {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 6px;
  }
  .tile {
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--dim);
    font-size: 1.4rem;
    font-weight: bold;
    color: var(--fg);
    text-transform: uppercase;
  }
  .tile.correct { background: var(--correct); border-color: var(--correct); color: #fff; }
  .tile.present { background: var(--present); border-color: var(--present); color: #fff; }
  .tile.absent  { background: var(--absent); border-color: var(--absent); color: #888; }
  #message {
    min-height: 1.4em;
    text-align: center;
    color: var(--amber);
    margin-bottom: 14px;
    font-size: 0.9rem;
  }
  #keyboard {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: center;
  }
  .kb-row { display: flex; gap: 5px; }
  .key {
    min-width: 28px;
    padding: 8px 6px;
    background: var(--panel);
    border: 1px solid var(--dim);
    color: var(--fg);
    font-family: inherit;
    font-size: 0.8rem;
    border-radius: 3px;
    cursor: pointer;
    text-transform: uppercase;
  }
  .key.correct { background: var(--correct); border-color: var(--correct); color: #fff; }
  .key.present { background: var(--present); border-color: var(--present); color: #fff; }
  .key.absent  { background: var(--absent); border-color: var(--absent); color: #555; }
  .key.wide { min-width: 52px; }
  #newgame {
    display: block;
    margin: 18px auto 0;
    background: transparent;
    border: 1px solid var(--fg);
    color: var(--fg);
    font-family: inherit;
    padding: 8px 16px;
    border-radius: 4px;
    cursor: pointer;
  }
  #newgame:hover { background: var(--fg); color: var(--bg); }
</style>
</head>
<body>
  <h1>WORDLE</h1>
  <div class="subtitle">attempt <span id="attemptCount">0</span>/6</div>
  <div class="terminal">
    <div id="board"></div>
    <div id="message">&nbsp;</div>
    <div id="keyboard"></div>
  </div>
  <button id="newgame">New Game</button>

<script>
const WORD_LENGTH = 5;
const MAX_ATTEMPTS = 6;
const ROWS = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];

let attempts = [];
let currentGuess = "";
let gameOver = false;
let keyStatus = {};

const boardEl = document.getElementById("board");
const messageEl = document.getElementById("message");
const keyboardEl = document.getElementById("keyboard");
const attemptCountEl = document.getElementById("attemptCount");

function buildBoard() {
  boardEl.innerHTML = "";
  for (let r = 0; r < MAX_ATTEMPTS; r++) {
    const row = document.createElement("div");
    row.className = "row";
    row.id = "row-" + r;
    for (let c = 0; c < WORD_LENGTH; c++) {
      const tile = document.createElement("div");
      tile.className = "tile";
      tile.id = "tile-" + r + "-" + c;
      row.appendChild(tile);
    }
    boardEl.appendChild(row);
  }
}

function buildKeyboard() {
  keyboardEl.innerHTML = "";
  ROWS.forEach((row, i) => {
    const kbRow = document.createElement("div");
    kbRow.className = "kb-row";
    if (i === 2) kbRow.appendChild(makeKey("ENTER", true));
    for (const ch of row) kbRow.appendChild(makeKey(ch, false));
    if (i === 2) kbRow.appendChild(makeKey("DEL", true));
    keyboardEl.appendChild(kbRow);
  });
}

function makeKey(label, wide) {
  const btn = document.createElement("button");
  btn.className = "key" + (wide ? " wide" : "");
  btn.textContent = label;
  btn.dataset.key = label;
  btn.addEventListener("click", () => handleKey(label));
  return btn;
}

function renderBoard() {
  attempts.forEach((a, r) => {
    for (let c = 0; c < WORD_LENGTH; c++) {
      const tile = document.getElementById("tile-" + r + "-" + c);
      tile.textContent = a.word[c];
      tile.className = "tile " + a.result[c];
    }
  });
  const activeRow = attempts.length;
  if (activeRow < MAX_ATTEMPTS) {
    for (let c = 0; c < WORD_LENGTH; c++) {
      const tile = document.getElementById("tile-" + activeRow + "-" + c);
      tile.textContent = currentGuess[c] || "";
      tile.className = "tile";
    }
  }
  attemptCountEl.textContent = attempts.length;
}

function renderKeyboard() {
  document.querySelectorAll(".key").forEach((btn) => {
    const k = btn.dataset.key;
    if (k.length === 1 && keyStatus[k]) {
      btn.className = "key " + keyStatus[k];
    }
  });
}

const RANK = { absent: 0, present: 1, correct: 2 };
function updateKeyStatus(word, result) {
  for (let i = 0; i < word.length; i++) {
    const letter = word[i];
    const status = result[i];
    if (!keyStatus[letter] || RANK[status] > RANK[keyStatus[letter]]) {
      keyStatus[letter] = status;
    }
  }
}

function setMessage(text) {
  messageEl.textContent = text || "\\u00a0";
}

async function newGame() {
  const res = await fetch("/api/new", { method: "POST" });
  const data = await res.json();
  attempts = [];
  currentGuess = "";
  gameOver = false;
  keyStatus = {};
  buildBoard();
  buildKeyboard();
  renderBoard();
  renderKeyboard();
  setMessage("Guess the " + data.wordLength + "-letter word.");
}

async function submitGuess() {
  if (currentGuess.length !== WORD_LENGTH) {
    setMessage("Not enough letters.");
    return;
  }
  const res = await fetch("/api/guess", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word: currentGuess }),
  });
  const data = await res.json();

  if (data.error) {
    setMessage(data.error);
    return;
  }

  attempts.push({ word: currentGuess, result: data.result });
  updateKeyStatus(currentGuess, data.result);
  currentGuess = "";
  renderBoard();
  renderKeyboard();

  if (data.gameOver) {
    gameOver = true;
    setMessage(data.won ? "You win!" : "Out of guesses. The word was " + data.word + ".");
  } else {
    setMessage("");
  }
}

function handleKey(key) {
  if (gameOver) return;
  if (key === "ENTER") {
    submitGuess();
  } else if (key === "DEL") {
    currentGuess = currentGuess.slice(0, -1);
    renderBoard();
  } else if (/^[A-Z]$/.test(key) && currentGuess.length < WORD_LENGTH) {
    currentGuess += key;
    renderBoard();
  }
}

document.addEventListener("keydown", (e) => {
  const key = e.key.toUpperCase();
  if (key === "ENTER") handleKey("ENTER");
  else if (key === "BACKSPACE") handleKey("DEL");
  else if (/^[A-Z]$/.test(key)) handleKey(key);
});

document.getElementById("newgame").addEventListener("click", newGame);

newGame();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML_PAGE
