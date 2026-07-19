import base64
import hashlib
import hmac
import importlib.util
import json
import os
import random
import time
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
ANSWERS = wordle_bundled.ANSWERS

app = FastAPI()

COOKIE_NAME = "wordle_state"

# Game state (target word, attempts, timer, hints used) is signed and stored
# entirely in the cookie rather than in server memory. Vercel's Python
# functions aren't guaranteed to route two requests from the same browser to
# the same warm instance, so an in-memory session dict can silently vanish
# mid-game -- the client would then get a fresh, unrelated target scored
# against old guesses, producing tile colors that don't match anything the
# player typed. A signed cookie makes every request self-contained.
SECRET_KEY = os.environ.get("WORDLE_SECRET_KEY", "worldle-demo-static-secret-key")


class GuessRequest(BaseModel):
    word: str


class HintRequest(BaseModel):
    level: int


def _sign(payload_b64: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def _encode_state(state: dict) -> str:
    raw = json.dumps(state, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{payload_b64}.{_sign(payload_b64)}"


def _decode_state(cookie_value: Optional[str]) -> Optional[dict]:
    if not cookie_value or "." not in cookie_value:
        return None
    payload_b64, _, sig = cookie_value.partition(".")
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(raw)
    except Exception:
        return None


def _new_state() -> dict:
    return {
        "target": random_word().upper(),
        "attempts": [],
        "game_over": False,
        "won": False,
        "started": time.time(),
        "penalty": 0,
        "hints": {},
    }


def _set_state_cookie(response: Response, state: dict) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _encode_state(state),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,
    )


def _green_positions(attempts: list) -> set:
    positions = set()
    for attempt in attempts:
        for i, status in enumerate(attempt["result"]):
            if status == "correct":
                positions.add(i)
    return positions


def _matching_words(attempts: list) -> list:
    green = [None] * WORD_LENGTH
    yellow_excluded = [set() for _ in range(WORD_LENGTH)]
    included = set()
    excluded = set()

    for attempt in attempts:
        word = attempt["word"]
        for i, (letter, status) in enumerate(zip(word, attempt["result"])):
            letter = letter.lower()
            if status == "correct":
                green[i] = letter
                included.add(letter)
            elif status == "present":
                yellow_excluded[i].add(letter)
                included.add(letter)
            elif status == "absent":
                excluded.add(letter)
    excluded -= included

    guessed = {a["word"].lower() for a in attempts}

    def matches(word: str) -> bool:
        for i, letter in enumerate(word):
            if green[i] and letter != green[i]:
                return False
            if letter in yellow_excluded[i]:
                return False
            if letter in excluded:
                return False
        return all(letter in word for letter in included)

    return [w.upper() for w in ANSWERS if w not in guessed and matches(w)]


@app.post("/api/new")
def new_game() -> JSONResponse:
    state = _new_state()
    response = JSONResponse(
        {
            "wordLength": WORD_LENGTH,
            "maxAttempts": MAX_ATTEMPTS,
            "startedAt": int(state["started"] * 1000),
            "penaltySeconds": 0,
            "hints": {},
        }
    )
    _set_state_cookie(response, state)
    return response


@app.post("/api/guess")
def guess(payload: GuessRequest, request: Request) -> JSONResponse:
    state = _decode_state(request.cookies.get(COOKIE_NAME))
    word = payload.word.strip().upper()

    def respond(state: dict, **extra) -> JSONResponse:
        body = {
            "result": None,
            "gameOver": state["game_over"],
            "won": state["won"],
            "attempts": state["attempts"],
            "error": None,
            "word": state["target"] if state["game_over"] else None,
            "startedAt": int(state["started"] * 1000),
            "penaltySeconds": state["penalty"],
            "hints": state["hints"],
        }
        body.update(extra)
        response = JSONResponse(body)
        _set_state_cookie(response, state)
        return response

    if state is None:
        return JSONResponse({"error": "No game in progress. Start a new game."}, status_code=400)

    if state["game_over"]:
        return respond(state, error="Game is already over. Start a new game.")

    if len(word) != WORD_LENGTH or not word.isalpha():
        return respond(state, error=f"Guess must be a {WORD_LENGTH}-letter word.")

    if not is_valid_guess(word):
        return respond(state, error=f"'{word}' isn't in the word list.")

    result = score_guess(word, state["target"])
    state["attempts"].append({"word": word, "result": result})

    won = word == state["target"]
    out_of_attempts = len(state["attempts"]) >= MAX_ATTEMPTS
    if won or out_of_attempts:
        state["game_over"] = True
        state["won"] = won

    return respond(state, result=result)


@app.post("/api/hint")
def hint(payload: HintRequest, request: Request) -> JSONResponse:
    state = _decode_state(request.cookies.get(COOKIE_NAME))
    if state is None:
        return JSONResponse({"error": "No game in progress. Start a new game."}, status_code=400)
    if state["game_over"]:
        return JSONResponse({"error": "Game is already over."}, status_code=400)

    level = payload.level

    if level == 1:
        taken = _green_positions(state["attempts"]) | {int(p) for p in state["hints"]}
        available = [i for i in range(WORD_LENGTH) if i not in taken]
        if not available:
            return JSONResponse({"error": "Every letter is already revealed."}, status_code=400)
        position = random.choice(available)
        letter = state["target"][position]
        state["hints"][str(position)] = letter
        state["penalty"] += 15
        body = {"level": 1, "position": position, "letter": letter}
    elif level == 2:
        matches = _matching_words(state["attempts"])
        sample = random.sample(matches, min(5, len(matches))) if matches else []
        state["penalty"] += 30
        body = {"level": 2, "words": sample, "total": len(matches)}
    elif level == 3:
        matches = _matching_words(state["attempts"])
        state["penalty"] += 60
        body = {"level": 3, "words": matches, "total": len(matches)}
    else:
        return JSONResponse({"error": "Invalid hint level."}, status_code=400)

    body["penaltySeconds"] = state["penalty"]
    body["hints"] = state["hints"]
    response = JSONResponse(body)
    _set_state_cookie(response, state)
    return response


HTML_PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover" />
<title>WORDLE</title>
<style>
  :root {
    --bg-top: #0a0a23;
    --bg-bottom: #1a0533;
    --panel: rgba(255, 255, 255, 0.04);
    --panel-border: rgba(255, 255, 255, 0.08);
    --fg: #eef0ff;
    --dim: #8a86b8;
    --cyan: #2dd9ff;
    --magenta: #ff4fd8;
    --gold: #ffd166;
    --correct: #17e0a1;
    --present: #ffd166;
    --absent: #3a3552;
  }
  * { box-sizing: border-box; }
  html, body {
    height: 100%;
    height: -webkit-fill-available;
    height: 100dvh;
    margin: 0;
    background: var(--bg-bottom);
    overscroll-behavior: none;
    overflow: hidden;
  }
  html {
    touch-action: manipulation;
    -webkit-text-size-adjust: 100%;
  }
  body {
    background: radial-gradient(circle at 50% -10%, #2a1250 0%, var(--bg-top) 45%, var(--bg-bottom) 100%);
    color: var(--fg);
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: clamp(14px, 4vw, 32px) 12px calc(40px + env(safe-area-inset-bottom));
    overflow-x: hidden;
    touch-action: manipulation;
  }
  .topbar {
    width: 100%;
    max-width: 420px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  .title-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  h1 {
    background: linear-gradient(90deg, var(--cyan), var(--magenta));
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    letter-spacing: 0.35em;
    margin: 0;
    font-size: clamp(1.4rem, 6vw, 1.9rem);
    font-weight: 800;
  }
  #hintBtn {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 1px solid var(--panel-border);
    background: var(--panel);
    color: var(--gold);
    font-weight: 700;
    cursor: pointer;
    line-height: 1;
    flex-shrink: 0;
    touch-action: manipulation;
  }
  #hintBtn:hover { border-color: var(--gold); box-shadow: 0 0 10px rgba(255, 209, 102, 0.5); }
  #timer {
    font-variant-numeric: tabular-nums;
    color: var(--cyan);
    font-weight: 600;
    font-size: 1rem;
    text-shadow: 0 0 10px rgba(45, 217, 255, 0.5);
  }
  .terminal {
    width: 100%;
    max-width: 420px;
    min-height: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    backdrop-filter: blur(6px);
    border: 1px solid var(--panel-border);
    border-radius: 16px;
    box-shadow: 0 0 40px rgba(45, 217, 255, 0.08), 0 8px 30px rgba(0, 0, 0, 0.4);
    padding: 20px;
    position: relative;
    touch-action: manipulation;
  }
  #board {
    display: grid;
    grid-template-rows: repeat(6, minmax(0, 1fr));
    gap: 6px;
    margin-bottom: 18px;
    min-height: 0;
    perspective: 500px;
    touch-action: manipulation;
  }
  .row {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 6px;
    min-width: 0;
    min-height: 0;
    touch-action: manipulation;
  }
  .tile {
    aspect-ratio: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    touch-action: manipulation;
    font-size: clamp(1.1rem, 5vw, 1.5rem);
    font-weight: 700;
    color: var(--fg);
    text-transform: uppercase;
    background: rgba(255, 255, 255, 0.02);
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .tile.filled { border-color: var(--dim); }
  .tile.hinted {
    border-color: var(--gold);
    box-shadow: 0 0 12px rgba(255, 209, 102, 0.6);
    color: var(--gold);
  }
  .tile.flip { animation: flipTile 0.5s ease forwards; }
  @keyframes flipTile {
    0% { transform: rotateY(0deg); }
    50% { transform: rotateY(90deg); }
    100% { transform: rotateY(0deg); }
  }
  .tile.correct { background: var(--correct); border-color: var(--correct); color: #052e22; box-shadow: 0 0 16px rgba(23, 224, 161, 0.55); }
  .tile.present { background: var(--present); border-color: var(--present); color: #3a2900; box-shadow: 0 0 16px rgba(255, 209, 102, 0.5); }
  .tile.absent  { background: var(--absent); border-color: var(--absent); color: #9a94c0; }
  .top-info {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  #attemptInfo {
    color: var(--dim);
    font-size: 0.82rem;
    font-weight: 600;
  }
  .status-dot {
    color: var(--dim);
    opacity: 0.6;
  }
  #message {
    min-height: 1.4em;
    text-align: center;
    color: var(--magenta);
    font-size: 0.85rem;
    font-weight: 600;
    flex-shrink: 0;
    width: 100%;
    max-width: 420px;
  }
  #message.top-msg {
    margin-bottom: 4px;
  }
  #message.inline-msg {
    margin: 0;
    min-height: 0;
  }
  #keyboard {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: center;
    flex-shrink: 0;
    touch-action: manipulation;
  }
  .kb-row { display: flex; gap: 5px; width: 100%; justify-content: center; touch-action: manipulation; }
  .key {
    min-width: 28px;
    padding: clamp(8px, 3vw, 14px) 6px;
    flex: 1;
    max-width: 40px;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    color: var(--fg);
    font-family: inherit;
    font-size: 0.8rem;
    font-weight: 600;
    border-radius: 6px;
    cursor: pointer;
    text-transform: uppercase;
    touch-action: manipulation;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
  }
  .key.correct { background: var(--correct); border-color: var(--correct); color: #052e22; }
  .key.present { background: var(--present); border-color: var(--present); color: #3a2900; }
  .key.absent  { background: var(--absent); border-color: var(--absent); color: #6a648f; }
  .key:disabled { cursor: not-allowed; }
  .key.wide { flex: 1.6; max-width: 64px; font-size: 0.68rem; }
  #newgame {
    display: block;
    flex-shrink: 0;
    margin: 18px auto 0;
    background: linear-gradient(90deg, var(--cyan), var(--magenta));
    border: none;
    color: #0a0a23;
    font-family: inherit;
    font-weight: 700;
    padding: 10px 20px;
    border-radius: 8px;
    cursor: pointer;
    touch-action: manipulation;
  }
  #newgame:hover { filter: brightness(1.1); box-shadow: 0 0 20px rgba(255, 79, 216, 0.4); }

  .site-footer {
    flex-shrink: 0;
    margin-top: 22px;
    font-size: 0.72rem;
    color: var(--dim);
    text-align: center;
    opacity: 0.7;
  }
  .site-footer a {
    color: var(--dim);
    text-decoration: none;
  }
  .site-footer a:hover { color: var(--cyan); }

  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(5, 3, 20, 0.7);
    backdrop-filter: blur(3px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 16px;
  }
  .overlay.hidden { display: none; }
  .modal {
    width: 100%;
    max-width: 380px;
    background: #170c34;
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    padding: 20px;
    box-shadow: 0 0 40px rgba(255, 79, 216, 0.15);
  }
  .modal h2 {
    margin: 0 0 14px;
    font-size: 1.05rem;
    color: var(--gold);
  }
  .modal-option {
    display: block;
    width: 100%;
    text-align: left;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    color: var(--fg);
    padding: 12px 14px;
    border-radius: 10px;
    margin-bottom: 10px;
    cursor: pointer;
    font-family: inherit;
    touch-action: manipulation;
  }
  .modal-option:hover { border-color: var(--cyan); }
  .modal-option small { display: block; color: var(--dim); margin-top: 3px; }
  .modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px; }
  .modal-actions button {
    padding: 8px 16px;
    border-radius: 8px;
    border: 1px solid var(--panel-border);
    background: var(--panel);
    color: var(--fg);
    cursor: pointer;
    font-family: inherit;
    touch-action: manipulation;
  }
  .modal-actions button.confirm { background: var(--magenta); border-color: var(--magenta); color: #250014; font-weight: 700; }
  .word-list { display: flex; flex-wrap: wrap; gap: 6px; max-height: 220px; overflow-y: auto; margin: 10px 0; }
  .word-chip {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    padding: 5px 10px;
    border-radius: 6px;
    font-size: 0.85rem;
    letter-spacing: 0.05em;
    cursor: pointer;
    touch-action: manipulation;
  }
  .word-chip:hover { border-color: var(--cyan); color: var(--cyan); }
  .modal-close {
    display: block;
    margin: 10px 0 0 auto;
    background: none;
    border: none;
    color: var(--cyan);
    cursor: pointer;
    font-family: inherit;
    touch-action: manipulation;
  }

  #sparkles {
    position: fixed;
    inset: 0;
    pointer-events: none;
    overflow: hidden;
    z-index: 40;
  }
  .sparkle {
    position: absolute;
    bottom: -10px;
    font-size: 1.4rem;
    animation: riseFade linear forwards;
  }
  @keyframes riseFade {
    0% { transform: translateY(0) rotate(0deg); opacity: 1; }
    100% { transform: translateY(-100vh) rotate(360deg); opacity: 0; }
  }

  @media (max-width: 380px) {
    h1 { letter-spacing: 0.22em; }
  }

  @media (max-height: 700px) {
    body { padding: clamp(8px, 2vw, 16px); padding-bottom: calc(clamp(8px, 2vw, 16px) + env(safe-area-inset-bottom)); }
    .terminal { padding: 12px; }
    #board { gap: 4px; margin-bottom: 10px; }
    .row { gap: 4px; }
    .tile { font-size: clamp(1rem, 4.5vw, 1.4rem); }
    #message.top-msg { margin-bottom: 4px; }
    #keyboard { gap: 4px; }
    .kb-row { gap: 4px; }
    .key { padding: clamp(6px, 2.4vw, 12px) 4px; font-size: 0.75rem; }
    #newgame { margin: 8px auto 0; padding: 8px 18px; }
    .site-footer { display: none; }
  }

  @media (max-height: 580px) {
    body { padding: 4px; padding-bottom: calc(4px + env(safe-area-inset-bottom)); }
    .terminal { padding: 6px; }
    #board { gap: 2px; margin-bottom: 6px; }
    .row { gap: 2px; }
    .tile { font-size: clamp(0.85rem, 4vw, 1.2rem); }
    #keyboard { gap: 2px; }
    .kb-row { gap: 2px; }
    .key { padding: 4px 3px; font-size: 0.65rem; }
    #newgame { margin: 4px auto 0; padding: 6px 14px; font-size: 0.8rem; }
  }
</style>
</head>
<body>
  <div class="topbar">
    <div class="title-row">
      <h1>WORDLE</h1>
      <button id="hintBtn" title="Hints">?</button>
    </div>
    <div class="top-info">
      <span id="attemptInfo">0/6</span>
      <span class="status-dot">&middot;</span>
      <span id="timer">00:00</span>
    </div>
  </div>
  <div id="message" class="top-msg">&nbsp;</div>
  <div class="terminal">
    <div id="board"></div>
    <div id="keyboard"></div>
  </div>
  <button id="newgame">New Game</button>
  <div id="sparkles"></div>
  <footer class="site-footer">Created by Mindster &middot; <a href="https://mindster.space" target="_blank" rel="noopener">Moca Mind</a></footer>

  <div class="overlay hidden" id="hintOverlay">
    <div class="modal" id="hintModal"></div>
  </div>

<script>
const WORD_LENGTH = 5;
const MAX_ATTEMPTS = 6;
const ROWS = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];

let attempts = [];
let currentGuess = "";
let gameOver = false;
let keyStatus = {};
let hintedTiles = {};
let startedAt = Date.now();
let penaltySeconds = 0;
let timerHandle = null;
let submitting = false;
let renderGen = 0;

const boardEl = document.getElementById("board");
const messageEl = document.getElementById("message");
const keyboardEl = document.getElementById("keyboard");
const attemptInfoEl = document.getElementById("attemptInfo");
const timerEl = document.getElementById("timer");
const hintOverlay = document.getElementById("hintOverlay");
const hintModal = document.getElementById("hintModal");
const sparklesEl = document.getElementById("sparkles");

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
  btn.addEventListener("mousedown", (e) => e.preventDefault());
  btn.addEventListener("click", () => {
    if (btn.disabled) return; // guard against disabled-button click quirks on some mobile browsers
    handleKey(label);
  });
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
      const typed = currentGuess[c];
      if (typed) {
        tile.textContent = typed;
        tile.className = "tile filled";
      } else if (hintedTiles[c] !== undefined) {
        tile.textContent = hintedTiles[c];
        tile.className = "tile hinted";
      } else {
        tile.textContent = "";
        tile.className = "tile";
      }
    }
  }
  attemptInfoEl.textContent = attempts.length + "/6";
}

function animateLastRow() {
  const r = attempts.length - 1;
  const a = attempts[r];
  for (let c = 0; c < WORD_LENGTH; c++) {
    const tile = document.getElementById("tile-" + r + "-" + c);
    tile.textContent = a.word[c];
    tile.className = "tile filled flip";
    tile.style.animationDelay = (c * 200) + "ms";
    setTimeout(() => {
      tile.className = "tile flip " + a.result[c];
      tile.style.animationDelay = (c * 200) + "ms";
    }, c * 200 + 250);
  }
}

function renderKeyboard() {
  document.querySelectorAll(".key").forEach((btn) => {
    const k = btn.dataset.key;
    if (k.length === 1 && keyStatus[k]) {
      btn.className = "key " + keyStatus[k] + (btn.classList.contains("wide") ? " wide" : "");
    }
    btn.disabled = gameOver || (k.length === 1 && keyStatus[k] === "absent");
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
  messageEl.textContent = text || " ";
}

function formatClock(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}

function formatDuration(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return m > 0 ? m + "m" + s + "s" : s + "s";
}

function currentElapsed() {
  return Math.floor((Date.now() - startedAt) / 1000) + penaltySeconds;
}

function startTimer() {
  stopTimer();
  timerEl.textContent = formatClock(currentElapsed());
  timerHandle = setInterval(() => {
    timerEl.textContent = formatClock(currentElapsed());
  }, 1000);
}

function stopTimer() {
  if (timerHandle) {
    clearInterval(timerHandle);
    timerHandle = null;
  }
}

function applyServerState(data) {
  startedAt = data.startedAt;
  penaltySeconds = data.penaltySeconds || 0;
  hintedTiles = {};
  (Object.entries(data.hints || {})).forEach(([pos, letter]) => {
    hintedTiles[Number(pos)] = letter;
  });
}

function spawnSparkles() {
  const emojis = ["✨", "⭐", "🌟"];
  for (let i = 0; i < 30; i++) {
    const s = document.createElement("div");
    s.className = "sparkle";
    s.textContent = emojis[i % emojis.length];
    s.style.left = (i * 3.3) + "%";
    s.style.animationDuration = (1.5 + (i % 5) * 0.3) + "s";
    s.style.animationDelay = ((i % 7) * 0.08) + "s";
    sparklesEl.appendChild(s);
    setTimeout(() => s.remove(), 4000);
  }
}

async function newGame() {
  renderGen++; // invalidate any in-flight guess response / pending reveal-delay timer from the old game
  hintOverlay.classList.add("hidden");
  let data;
  try {
    const res = await fetch("/api/new", { method: "POST" });
    data = await res.json();
  } catch (err) {
    setMessage("Connection hiccup — tap New Game to try again.");
    return;
  }
  attempts = [];
  currentGuess = "";
  gameOver = false;
  keyStatus = {};
  applyServerState(data);
  buildBoard();
  buildKeyboard();
  renderBoard();
  renderKeyboard();
  setMessage("Guess the " + data.wordLength + "-letter word.");
  startTimer();
}

async function submitGuess() {
  if (submitting) return;
  if (currentGuess.length !== WORD_LENGTH) {
    setMessage("Not enough letters.");
    return;
  }
  submitting = true;
  const guessedWord = currentGuess;
  const gen = renderGen;
  let data;
  try {
    const res = await fetch("/api/guess", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: guessedWord }),
    });
    data = await res.json();
  } catch (err) {
    // A dropped connection or a non-JSON error page (cold start, flaky mobile
    // network) must not silently eat the guess -- without this, a winning
    // guess could vanish with no message, no board update, and no way to
    // retry it since currentGuess/submitting are left in a stuck state.
    submitting = false;
    if (gen === renderGen) setMessage("Connection hiccup — try that guess again.");
    return;
  }
  submitting = false;

  // A new game may have started while this request was in flight -- discard
  // the now-stale response instead of applying it on top of the fresh board.
  if (gen !== renderGen) return;

  if (data.error) {
    setMessage(data.error);
    return;
  }

  attempts.push({ word: guessedWord, result: data.result });
  updateKeyStatus(guessedWord, data.result);
  applyServerState(data);
  currentGuess = "";
  if (data.gameOver) gameOver = true;
  renderBoard();
  animateLastRow();
  renderKeyboard();

  const revealDelay = WORD_LENGTH * 200 + 300;

  if (data.gameOver) {
    stopTimer();
    const elapsed = currentElapsed();
    timerEl.textContent = formatClock(elapsed);
    setTimeout(() => {
      // A new game may have started during the reveal delay -- don't let this
      // stale win/loss message clobber whatever the new game is showing.
      if (gen !== renderGen) return;
      if (data.won) {
        setMessage("Solved in " + attempts.length + "/" + MAX_ATTEMPTS + " · " + formatDuration(elapsed));
        spawnSparkles();
      } else {
        setMessage("Out of guesses · " + formatDuration(elapsed) + ". The word was " + data.word + ".");
      }
    }, revealDelay);
  } else {
    setTimeout(() => {
      if (gen === renderGen) setMessage("");
    }, revealDelay);
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
  if (!hintOverlay.classList.contains("hidden")) return;
  const key = e.key.toUpperCase();
  if (key === "ENTER") handleKey("ENTER");
  else if (key === "BACKSPACE") handleKey("DEL");
  else if (/^[A-Z]$/.test(key)) handleKey(key);
});

const newGameBtn = document.getElementById("newgame");
newGameBtn.addEventListener("mousedown", (e) => e.preventDefault());
newGameBtn.addEventListener("click", newGame);

// --- Hint / cheat modal ---

const HINT_LEVELS = [
  { level: 1, label: "Hint", desc: "Reveal one random correct letter position.", penalty: 15 },
  { level: 2, label: "Show possible words", desc: "3-5 word suggestions based on the board.", penalty: 30 },
  { level: 3, label: "Show ALL valid words", desc: "Every remaining possible word.", penalty: 60 },
];

function openHintMenu() {
  if (gameOver) return;
  hintModal.innerHTML = "";
  const h2 = document.createElement("h2");
  h2.textContent = "Need a hand?";
  hintModal.appendChild(h2);
  HINT_LEVELS.forEach((opt) => {
    const btn = document.createElement("button");
    btn.className = "modal-option";
    btn.innerHTML = opt.label + "<small>" + opt.desc + " (+" + opt.penalty + "s)</small>";
    btn.addEventListener("click", () => openHintConfirm(opt));
    hintModal.appendChild(btn);
  });
  const close = document.createElement("button");
  close.className = "modal-close";
  close.textContent = "Close";
  close.addEventListener("click", () => hintOverlay.classList.add("hidden"));
  hintModal.appendChild(close);
  hintOverlay.classList.remove("hidden");
}

function openHintConfirm(opt) {
  hintModal.innerHTML = "";
  const h2 = document.createElement("h2");
  h2.textContent = "Use " + opt.label + "? (+" + opt.penalty + "s penalty)";
  hintModal.appendChild(h2);
  const actions = document.createElement("div");
  actions.className = "modal-actions";
  const no = document.createElement("button");
  no.textContent = "No";
  no.addEventListener("click", openHintMenu);
  const yes = document.createElement("button");
  yes.className = "confirm";
  yes.textContent = "Yes";
  yes.addEventListener("click", () => useHint(opt.level));
  actions.appendChild(no);
  actions.appendChild(yes);
  hintModal.appendChild(actions);
}

async function useHint(level) {
  let data;
  try {
    const res = await fetch("/api/hint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level }),
    });
    data = await res.json();
  } catch (err) {
    hintModal.innerHTML = "<h2>Connection hiccup — try again</h2>";
    setTimeout(openHintMenu, 1200);
    return;
  }
  if (data.error) {
    hintModal.innerHTML = "<h2>" + data.error + "</h2>";
    setTimeout(openHintMenu, 1200);
    return;
  }
  penaltySeconds = data.penaltySeconds;
  timerEl.textContent = formatClock(currentElapsed());

  if (data.level === 1) {
    hintedTiles[data.position] = data.letter;
    renderBoard();
    hintOverlay.classList.add("hidden");
    return;
  }

  hintModal.innerHTML = "";
  const h2 = document.createElement("h2");
  h2.textContent = data.level === 2 ? "A few possibilities" : "All remaining words (" + data.total + ")";
  hintModal.appendChild(h2);
  const list = document.createElement("div");
  list.className = "word-list";
  if (data.words.length === 0) {
    const p = document.createElement("div");
    p.textContent = "No matches found.";
    list.appendChild(p);
  } else {
    data.words.forEach((w) => {
      const chip = document.createElement("span");
      chip.className = "word-chip";
      chip.textContent = w;
      chip.addEventListener("mousedown", (e) => e.preventDefault());
      chip.addEventListener("click", () => {
        if (gameOver) return;
        currentGuess = w;
        renderBoard();
        hintOverlay.classList.add("hidden");
        submitGuess();
      });
      list.appendChild(chip);
    });
  }
  hintModal.appendChild(list);
  const close = document.createElement("button");
  close.className = "modal-close";
  close.textContent = "Close";
  close.addEventListener("click", () => hintOverlay.classList.add("hidden"));
  hintModal.appendChild(close);
}

document.getElementById("hintBtn").addEventListener("click", openHintMenu);
hintOverlay.addEventListener("click", (e) => {
  if (e.target === hintOverlay) hintOverlay.classList.add("hidden");
});

newGame();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(HTML_PAGE, headers={"Cache-Control": "no-store"})
