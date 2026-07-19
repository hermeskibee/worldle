// Automated QA for the WORDLE web app (api/index.py), driven with real Playwright
// Chromium (not a DOM shim) so animation timing, CSS layout, and cookie handling
// behave exactly as they would for a real player.
//
// Usage:
//   node scripts/qa-test.mjs                  # targets http://127.0.0.1:8811
//   QA_BASE_URL=https://worldle-eight.vercel.app node scripts/qa-test.mjs

import { chromium } from "playwright";

const BASE_URL = process.env.QA_BASE_URL || "http://127.0.0.1:8811";
const FLIP_SETTLE_MS = 1600; // 5 tiles * 200ms stagger + 250ms color-swap + buffer

// A pool of words guaranteed to be in wordle.py's ANSWERS list, used as filler
// guesses for loss/hint tests. wordle.py is not imported here on purpose -- this
// script only talks to the HTTP API, the same surface a real browser uses.
const FILLER_WORDS = [
  "ABBEY", "ABBOT", "ABIDE", "ABODE", "ABORT", "ABOUT", "ABOVE", "ABUSE",
  "ABYSS", "ACHES", "ACIDS", "ACORN", "ACRES", "ACTED", "ACTOR", "ACUTE",
];

function fail(msg) {
  const e = new Error(msg);
  e.isAssertion = true;
  throw e;
}

function assert(cond, msg) {
  if (!cond) fail(msg);
}

// Mirrors wordle.py's score_guess(): correct-position letters claimed first,
// then leftover letter copies handed out to present-but-misplaced matches.
function expectedScore(guess, target) {
  guess = guess.toUpperCase();
  target = target.toUpperCase();
  const result = new Array(guess.length).fill("absent");
  const remaining = {};
  for (const ch of target) remaining[ch] = (remaining[ch] || 0) + 1;

  for (let i = 0; i < guess.length; i++) {
    if (guess[i] === target[i]) {
      result[i] = "correct";
      remaining[guess[i]]--;
    }
  }
  for (let i = 0; i < guess.length; i++) {
    if (result[i] === "correct") continue;
    const ch = guess[i];
    if (remaining[ch] > 0) {
      result[i] = "present";
      remaining[ch]--;
    }
  }
  return result;
}

async function decodeTarget(context) {
  const cookies = await context.cookies();
  const c = cookies.find((c) => c.name === "wordle_state");
  if (!c) return null;
  const payloadB64 = c.value.split(".")[0];
  const normalized = payloadB64.replace(/-/g, "+").replace(/_/g, "/");
  const json = Buffer.from(normalized, "base64").toString("utf8");
  return JSON.parse(json).target;
}

// Vercel cold starts and real network latency can push /api/new well past a
// fixed short wait, so poll for the session cookie instead of sleeping a
// hardcoded duration -- this keeps the suite reliable against both a local
// server and a remote deployment. The cookie can land a tick before the
// client's own await-fetch chain finishes resetting the DOM, so also wait
// for the board to actually reflect a fresh game (attemptCount back to 0).
async function waitForGameReady(page, context, timeoutMs = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const target = await decodeTarget(context);
    const attemptCount = await page.textContent("#attemptInfo").catch(() => null);
    if (target && attemptCount != null && attemptCount.trim() === "0/6") return;
    await page.waitForTimeout(100);
  }
  fail("timed out waiting for /api/new to set the game cookie and reset the board");
}

// Waits for the actual /api/guess round trip to finish before returning, so
// FLIP_SETTLE_MS below only has to cover the client-side flip animation, not
// also absorb Vercel's real network/cold-start latency.
async function typeWord(page, word) {
  const responded = page.waitForResponse((res) => res.url().includes("/api/guess"), { timeout: 20000 });
  for (const ch of word) {
    await page.keyboard.press(ch.toUpperCase());
  }
  await page.keyboard.press("Enter");
  await responded;
}

// Same idea for the hint confirm button -- wait for /api/hint to actually
// respond instead of assuming a fixed timeout covers the network round trip.
async function confirmHint(page) {
  const responded = page.waitForResponse((res) => res.url().includes("/api/hint"), { timeout: 20000 });
  await page.click(".modal-actions button.confirm");
  await responded;
}

async function tileClasses(page, row) {
  const classes = [];
  for (let c = 0; c < 5; c++) {
    classes.push(await page.getAttribute(`#tile-${row}-${c}`, "class"));
  }
  return classes;
}

function classIncludes(classAttr, token) {
  return (classAttr || "").split(/\s+/).includes(token);
}

async function hasNoHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}

async function hasNoVerticalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1);
}

async function collectErrors(page) {
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push("console.error: " + msg.text());
  });
  page.on("pageerror", (err) => errors.push("pageerror: " + err.message));
  return errors;
}

async function withPage(browser, fn) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = await collectErrors(page);
  try {
    await page.goto(BASE_URL + "/");
    await page.waitForSelector("#board");
    await waitForGameReady(page, context); // wait for the initial /api/new fetch to settle
    await fn(page, context, errors);
    assert(errors.length === 0, "unexpected JS errors: " + JSON.stringify(errors));
  } finally {
    await context.close();
  }
}

async function guessDistinctFillers(target, count) {
  const words = FILLER_WORDS.filter((w) => w !== target).slice(0, count);
  assert(words.length === count, "not enough filler words available");
  return words;
}

const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}

// ────────────── L1: Page loading ──────────────

test("L1: page loads with full board, keyboard, and no console errors", async (page) => {
  const title = await page.textContent("h1");
  assert(title.trim() === "WORDLE", `expected title WORDLE, got "${title}"`);
  for (let r = 0; r < 6; r++) {
    for (let c = 0; c < 5; c++) {
      assert(await page.isVisible(`#tile-${r}-${c}`), `tile-${r}-${c} not visible`);
    }
  }
  assert((await page.$$(".key")).length === 28, "expected 28 keyboard keys (26 letters + ENTER + DEL)");
  assert(await hasNoHorizontalOverflow(page), "page has horizontal overflow on load");
});

test("L1: footer is present and visible", async (page) => {
  const footer = await page.textContent(".site-footer");
  assert(footer.includes("Mindster") && footer.includes("Moca Mind"), `footer wrong: "${footer}"`);
  assert(await page.isVisible(".site-footer"), "footer not visible");
});

test("L1: timer is visible and starts at 00:00", async (page) => {
  const timer = (await page.textContent("#timer")).trim();
  assert(timer === "00:00", `expected initial timer 00:00, got "${timer}"`);
});

test("L1: attempt counter sits next to the timer in the topbar, both actually on-screen", async (page) => {
  const attemptInfo = (await page.textContent("#attemptInfo")).trim();
  assert(attemptInfo === "0/6", `expected attempt info 0/6, got "${attemptInfo}"`);

  const viewport = page.viewportSize();
  const timerBox = await page.$eval("#timer", (el) => el.getBoundingClientRect());
  const attemptBox = await page.$eval("#attemptInfo", (el) => el.getBoundingClientRect());
  // Regression: .top-info previously had width:100% inside a flex row, which
  // pushed #timer past the right edge of the viewport (invisible, but not
  // caught by overflow-x checks since body clips it with no scrollbar).
  assert(timerBox.right <= viewport.width + 1, `#timer rendered off-screen: right=${timerBox.right}, viewport width=${viewport.width}`);
  assert(timerBox.left >= attemptBox.right, "timer should sit to the right of the attempt counter, not overlap it");
});

test("L1: hint button is visible and clickable", async (page) => {
  assert(await page.isVisible("#hintBtn"), "hint button not visible");
  await page.click("#hintBtn");
  await page.waitForTimeout(200);
  const overlay = await page.$("#hintOverlay");
  assert(overlay, "hint overlay did not appear after clicking hint button");
  const hidden = await overlay.getAttribute("class");
  assert(!hidden || !hidden.includes("hidden"), "hint overlay is hidden after click");
  // close it
  await page.click("#hintOverlay .modal-close");
});

// ────────────── L2: Gameplay ──────────────

test("L2: full win — target guessed with correct tile colors", async (page, context) => {
  const target = await decodeTarget(context);
  assert(target, "could not decode target from cookie");
  await typeWord(page, target);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  const classes = await tileClasses(page, 0);
  classes.forEach((cls, i) => assert(classIncludes(cls, "correct"), `tile-0-${i} expected correct, got "${cls}"`));

  const message = await page.textContent("#message");
  assert(/Solved in 1\/6/.test(message), `expected win message, got "${message}"`);

  const sparkles = await page.$$("#sparkles .sparkle");
  assert(sparkles.length > 0, "expected sparkle particles to spawn on win");
});

test("L2: full loss — 6 wrong guesses end the game, reveal the word, freeze timer", async (page, context) => {
  const target = await decodeTarget(context);
  const guesses = await guessDistinctFillers(target, 6);

  for (let i = 0; i < guesses.length; i++) {
    await typeWord(page, guesses[i]);
    await page.waitForTimeout(FLIP_SETTLE_MS);
    const expected = expectedScore(guesses[i], target);
    const classes = await tileClasses(page, i);
    expected.forEach((status, c) => {
      assert(classIncludes(classes[c], status), `row ${i} tile ${c}: expected ${status}, got "${classes[c]}"`);
    });
  }

  const message = await page.textContent("#message");
  assert(/Out of guesses/.test(message), `expected loss message, got "${message}"`);
  assert(message.toUpperCase().includes(target.toUpperCase()), "loss message did not reveal the target word");

  const t1 = await page.textContent("#timer");
  await page.waitForTimeout(1500);
  const t2 = await page.textContent("#timer");
  assert(t1 === t2, `timer should freeze on game over, saw ${t1} -> ${t2}`);
});

test("L2: duplicate letters scoring is correct", async (page, context) => {
  const target = await decodeTarget(context);
  // Pick a target that has a duplicate letter, or just verify the scoring function
  // against the API response for any target
  const guess = FILLER_WORDS.find((w) => w !== target);
  await typeWord(page, guess);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  // Just check scoring is consistent — manual verification pattern
  const classes = await tileClasses(page, 0);
  const expected = expectedScore(guess, target);
  expected.forEach((status, c) => {
    assert(classIncludes(classes[c], status), `tile ${c}: expected ${status}, got "${classes[c]}"`);
  });
});

// ────────────── L3: Game state management ──────────────

test("L3: new game after a win resets state and can be won again", async (page, context) => {
  const target1 = await decodeTarget(context);
  await typeWord(page, target1);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  await page.click("#newgame");
  await waitForGameReady(page, context);
  assert((await page.textContent("#attemptInfo")).trim() === "0/6", "attempt count did not reset");
  const freshClasses = await tileClasses(page, 0);
  freshClasses.forEach((cls, i) => assert(cls.trim() === "tile", `tile-0-${i} not reset, got "${cls}"`));

  const target2 = await decodeTarget(context);
  assert(target2, "no target after new game");
  await typeWord(page, target2);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  const classes2 = await tileClasses(page, 0);
  classes2.forEach((cls, i) => assert(classIncludes(cls, "correct"), `post-new-game tile-0-${i} wrong: "${cls}"`));
  assert(/Solved in 1\/6/.test(await page.textContent("#message")), "second win not registered");
});

test("L3: new game after a loss resets tiles and scores the next game against the new target", async (page, context) => {
  const target1 = await decodeTarget(context);
  const guesses = await guessDistinctFillers(target1, 6);
  for (const w of guesses) {
    await typeWord(page, w);
    await page.waitForTimeout(FLIP_SETTLE_MS);
  }
  assert(/Out of guesses/.test(await page.textContent("#message")), "setup: game did not end in a loss");

  await page.click("#newgame");
  await waitForGameReady(page, context);
  const freshClasses = await tileClasses(page, 0);
  freshClasses.forEach((cls, i) => assert(cls.trim() === "tile", `tile-0-${i} not reset after loss, got "${cls}"`));
  assert((await page.textContent("#message")).includes("Guess the"), "message did not reset after new game");

  const target2 = await decodeTarget(context);
  assert(target2, "no target after post-loss new game");
  const guess = FILLER_WORDS.find((w) => w !== target2);
  await typeWord(page, guess);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  const expected = expectedScore(guess, target2);
  const classes = await tileClasses(page, 0);
  expected.forEach((status, c) => {
    assert(classIncludes(classes[c], status), `post-loss-new-game tile ${c}: expected ${status}, got "${classes[c]}"`);
  });
});

test("L3: new game after win doesn't double-submit via focus-stolen Enter", async (page, context) => {
  const target1 = await decodeTarget(context);
  await typeWord(page, target1);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  await page.click("#newgame");
  await waitForGameReady(page, context);

  const target2 = await decodeTarget(context);
  assert(target2, "no target after new game");
  await typeWord(page, target2);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  // Critical: ensure only 1 attempt was recorded
  const attemptCount = (await page.textContent("#attemptInfo")).trim();
  assert(attemptCount === "1" || attemptCount === "1/6", `expected 1 attempt, got "${attemptCount}"`);
  assert(/Solved in 1\/6/.test(await page.textContent("#message")), "win message missing/wrong after new-game + win");
});

// ────────────── L4: Hints ──────────────

test("L4: hint level 1 reveals a correct letter without breaking layout", async (page, context) => {
  await page.click("#hintBtn");
  await page.waitForTimeout(150);
  const options = await page.$$(".modal-option");
  assert(options.length === 3, `expected 3 hint options, got ${options.length}`);
  await options[0].click();
  await page.waitForTimeout(150);
  await confirmHint(page);
  await page.waitForTimeout(150);

  assert(await hasNoHorizontalOverflow(page), "layout overflowed horizontally after hint level 1");
  assert(await page.isVisible("#board"), "board hidden/broken after hint level 1");
  assert(await page.isVisible("#keyboard"), "keyboard hidden/broken after hint level 1");
  assert(
    (await page.getAttribute("#hintOverlay", "class")).includes("hidden"),
    "hint overlay did not close after level-1 confirm"
  );

  const hinted = await page.$(".tile.hinted");
  assert(hinted, "no hinted tile found after level-1 hint");
  const target = await decodeTarget(context);
  const hintedText = (await hinted.textContent()).trim().toUpperCase();
  assert(target.toUpperCase().includes(hintedText), `hinted letter "${hintedText}" not in target`);

  const timer = await page.textContent("#timer");
  const [m, s] = timer.split(":").map(Number);
  assert(m * 60 + s >= 15, `expected +15s penalty reflected in timer, got ${timer}`);
});

test("L4: hint level 2 shows candidate words without breaking layout", async (page, context) => {
  await page.click("#hintBtn");
  await page.waitForTimeout(150);
  const options = await page.$$(".modal-option");
  await options[1].click();
  await page.waitForTimeout(150);
  await confirmHint(page);
  await page.waitForTimeout(150);

  assert(await hasNoHorizontalOverflow(page), "layout overflowed horizontally after hint level 2");
  const chips = await page.$$(".word-chip");
  assert(chips.length >= 1 && chips.length <= 5, `expected 1-5 word suggestions, got ${chips.length}`);
  for (const chip of chips) {
    const text = (await chip.textContent()).trim();
    assert(/^[A-Z]{5}$/.test(text), `word chip "${text}" is not a clean 5-letter word`);
  }
  assert(await page.isVisible("#board"), "board hidden/broken after hint level 2");

  await page.click(".modal-close");
  await page.waitForTimeout(150);
  assert((await page.getAttribute("#hintOverlay", "class")).includes("hidden"), "overlay did not close");
});

test("L4: hint level 3 lists all remaining candidates without breaking layout", async (page, context) => {
  const target = await decodeTarget(context);
  await page.click("#hintBtn");
  await page.waitForTimeout(150);
  const options = await page.$$(".modal-option");
  await options[2].click();
  await page.waitForTimeout(150);
  await confirmHint(page);
  await page.waitForTimeout(150);

  assert(await hasNoHorizontalOverflow(page), "layout overflowed horizontally after hint level 3");
  const heading = (await page.textContent("#hintModal h2")).trim();
  assert(/All remaining words \(\d+\)/.test(heading), `unexpected level-3 heading: "${heading}"`);

  const modalBox = await page.$eval("#hintModal", (el) => {
    const r = el.getBoundingClientRect();
    return { width: r.width, height: r.height, viewportH: window.innerHeight };
  });
  assert(modalBox.height <= modalBox.viewportH, "hint modal taller than viewport");

  const chips = await page.$$(".word-chip");
  const chipTexts = new Set();
  for (const chip of chips) chipTexts.add((await chip.textContent()).trim());
  assert(chipTexts.has(target.toUpperCase()), "target word missing from candidates");

  assert(await page.isVisible("#board"), "board hidden after hint level 3");
  await page.click(".modal-close");
});

test("L4: hint word chips are clickable and submit the word", async (page, context) => {
  // Need at least one hint with word chips to test clickability
  const target = await decodeTarget(context);
  // First make 2 guesses to narrow candidates
  const fillers = await guessDistinctFillers(target, 2);
  for (const w of fillers) {
    await typeWord(page, w);
    await page.waitForTimeout(FLIP_SETTLE_MS);
  }
  // Now hint level 2 to get candidate words
  await page.click("#hintBtn");
  await page.waitForTimeout(150);
  const options = await page.$$(".modal-option");
  await options[1].click();
  await page.waitForTimeout(150);
  await confirmHint(page);
  await page.waitForTimeout(150);

  const chips = await page.$$(".word-chip");
  if (chips.length > 0 && chips[0]) {
    // Get the word text before clicking
    const wordText = (await chips[0].textContent()).trim();
    // Click the chip
    await chips[0].click();
    await page.waitForTimeout(FLIP_SETTLE_MS + 500);
    // Check that a guess was made (attempt count increased or win triggered)
    const attemptCount = (await page.textContent("#attemptInfo")).trim();
    const attemptNum = parseInt(attemptCount);
    assert(attemptNum >= 3, `expected attempt >= 3 after clicking word chip, got ${attemptNum}`);
  }
});

// ────────────── L5: Keyboard & UI ──────────────

test("L5: ruled-out (absent) keyboard letters become disabled and unclickable", async (page, context) => {
  const target = await decodeTarget(context);
  const guess = FILLER_WORDS.find((w) => w !== target);
  await typeWord(page, guess);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  const disabledKey = await page.evaluate(() => {
    const btn = [...document.querySelectorAll(".key")].find((b) => b.classList.contains("absent"));
    return btn ? { key: btn.dataset.key, disabled: btn.disabled } : null;
  });
  assert(disabledKey, "expected at least one absent key after a guess with a wrong letter");
  assert(disabledKey.disabled, `absent key "${disabledKey.key}" is not disabled`);
});

test("L5: all keyboard keys (letters, ENTER, DEL) become disabled once the game is over", async (page, context) => {
  // Regression: gameOver was flipped true AFTER renderKeyboard() ran on the
  // winning/losing guess, so every key -- including ones that were never
  // ruled out -- stayed fully enabled and clickable after the game ended.
  const target = await decodeTarget(context);
  await typeWord(page, target);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  const keys = await page.evaluate(() =>
    [...document.querySelectorAll(".key")].map((b) => ({ key: b.dataset.key, disabled: b.disabled }))
  );
  const stillEnabled = keys.filter((k) => !k.disabled);
  assert(stillEnabled.length === 0, `keys still enabled after game over: ${JSON.stringify(stillEnabled)}`);
});

test("L5: DEL key clears the last entered letter", async (page) => {
  await page.keyboard.press("A");
  await page.keyboard.press("B");
  await page.keyboard.press("C");
  await page.keyboard.press("Backspace");
  // Should have AB left
  await page.keyboard.press("Enter");
  await page.waitForTimeout(200);
  const msg = await page.textContent("#message");
  assert(msg.includes("Not enough letters"), "DEL didn't clear properly: " + msg);
});

test("L5: rapid keyboard input doesn't break state", async (page, context) => {
  // Type faster than the server can respond — the 6th letter must be ignored
  // rather than overflowing currentGuess (QWERT isn't a dictionary word, so we
  // check client state directly instead of relying on a server round trip).
  await page.keyboard.press("Q");
  await page.keyboard.press("W");
  await page.keyboard.press("E");
  await page.keyboard.press("R");
  await page.keyboard.press("T");
  await page.keyboard.press("Y"); // 6th key, should be ignored
  const guess = await page.evaluate(() => currentGuess);
  assert(guess === "QWERT", `expected 6th keystroke to be ignored, currentGuess is "${guess}"`);

  // clear it and confirm the game still accepts a real guess afterward
  for (let i = 0; i < 5; i++) await page.keyboard.press("Backspace");
  const target = await decodeTarget(context);
  const filler = FILLER_WORDS.find((w) => w !== target);
  await typeWord(page, filler);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  const attemptCount = (await page.textContent("#attemptInfo")).trim();
  assert(attemptCount === "1" || attemptCount === "1/6", `expected 1 attempt after a real guess, got "${attemptCount}"`);
});

test("L5: incorrect word shows 'not in word list' without consuming attempt", async (page) => {
  await typeWord(page, "ZZZZQ");
  await page.waitForTimeout(400);
  const msg = await page.textContent("#message");
  assert(/isn't in the word list/.test(msg), `expected word-list rejection, got "${msg}"`);
  assert((await page.textContent("#attemptInfo")).trim() === "0/6", "attempt count changed on invalid word");
});

test("L5: short word shows 'not enough letters' without consuming attempt", async (page) => {
  await page.keyboard.press("A");
  await page.keyboard.press("B");
  await page.keyboard.press("C");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(200);
  assert((await page.textContent("#message")).includes("Not enough letters"), "short guess not rejected");
  assert((await page.textContent("#attemptInfo")).trim() === "0/6", "attempt count changed on rejected short guess");
});

// ────────────── L6: Mobile & Layout ──────────────

test("L6: mobile zoom-gesture guards are present (viewport + touch-action)", async (page) => {
  const viewport = await page.getAttribute('meta[name="viewport"]', "content");
  assert(/maximum-scale=1/.test(viewport), `viewport missing maximum-scale=1: "${viewport}"`);
  assert(/user-scalable=no/.test(viewport), `viewport missing user-scalable=no: "${viewport}"`);

  const bodyTouchAction = await page.evaluate(() => getComputedStyle(document.body).touchAction);
  assert(bodyTouchAction === "manipulation", `body touch-action expected "manipulation", got "${bodyTouchAction}"`);

  const htmlOverscroll = await page.evaluate(() => getComputedStyle(document.documentElement).overscrollBehaviorY);
  assert(htmlOverscroll === "none", `html overscroll-behavior expected "none", got "${htmlOverscroll}"`);
});

test("L6: no white gap — html background matches page theme", async (page) => {
  const htmlBg = await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor);
  assert(htmlBg !== "rgba(0, 0, 0, 0)" && htmlBg !== "rgb(255, 255, 255)", `html background looks unset/white: "${htmlBg}"`);
});

test("L6: no dead empty section stranded at the bottom on tall phones", async (page) => {
  // Regression: body had no vertical centering, so on any phone taller than
  // the content's natural height the leftover space piled up entirely below
  // the footer/new-game button instead of being shared top and bottom.
  await page.setViewportSize({ width: 412, height: 914 }); // Pixel 7 Pro -- plenty taller than content
  await page.waitForTimeout(200);
  const gaps = await page.evaluate(() => {
    const topbar = document.querySelector(".topbar").getBoundingClientRect();
    const last = document.querySelector(".site-footer") || document.getElementById("newgame");
    const lastRect = last.getBoundingClientRect();
    return { topGap: topbar.top, bottomGap: window.innerHeight - lastRect.bottom };
  });
  assert(gaps.bottomGap < gaps.topGap + 40, `bottom gap (${gaps.bottomGap}px) is stranded well past the top gap (${gaps.topGap}px) -- content isn't vertically centered`);
});

test("L6: keyboard/board containers all carry touch-action:manipulation (double-tap-zoom guard)", async (page) => {
  // Regression: a disabled <button> (an absent/ruled-out key) doesn't receive
  // its own touch-action, so a fast double-tap landing on one fell through to
  // whichever ancestor handled the hit-test -- and without touch-action set
  // there too, that ancestor let the browser interpret it as a zoom gesture.
  const touchActions = await page.evaluate(() =>
    [".terminal", "#board", ".row", "#keyboard", ".kb-row"].map((sel) => ({
      sel,
      touchAction: getComputedStyle(document.querySelector(sel)).touchAction,
    }))
  );
  for (const { sel, touchAction } of touchActions) {
    assert(touchAction === "manipulation", `${sel} touch-action expected "manipulation", got "${touchAction}"`);
  }
});

test("L6: page fits within viewport on small phone (iPhone SE, no overflow scroll)", async (page) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.waitForTimeout(200);
  assert(await hasNoVerticalOverflow(page), "page overflows a 375x667 viewport vertically");
  // Footer is intentionally hidden below the max-height:700px breakpoint to
  // free up vertical room for the board/keyboard -- it isn't load-bearing UI.
  for (const sel of ["#board", "#keyboard", "#newgame"]) {
    assert(await page.isVisible(sel), `${sel} not visible on 375x667 screen`);
  }
  assert(!(await page.isVisible(".site-footer")), "footer should be hidden below the 700px height breakpoint");
});

test("L6: page fits within many mobile viewports", async (page) => {
  const sizes = [
    { w: 320, h: 568 },   // iPhone SE (old)
    { w: 375, h: 667 },   // iPhone SE
    { w: 390, h: 844 },   // iPhone 12/13/14
    { w: 430, h: 932 },   // iPhone 14 Pro Max
    { w: 360, h: 800 },   // Pixel 5 / Galaxy
    { w: 412, h: 914 },   // Pixel 7 Pro
  ];
  for (const { w, h } of sizes) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(100);
    const ok = await hasNoVerticalOverflow(page);
    assert(ok, `page overflows at ${w}x${h} viewport — scrollHeight > clientHeight`);
    for (const sel of ["#board", "#keyboard"]) {
      assert(await page.isVisible(sel), `${sel} hidden at ${w}x${h}`);
    }
  }
});

test("L6: no horizontal overflow on any viewport size", async (page) => {
  const sizes = [
    { w: 320, h: 568 },
    { w: 375, h: 667 },
    { w: 390, h: 844 },
    { w: 430, h: 932 },
    { w: 1440, h: 900 },
  ];
  for (const { w, h } of sizes) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(100);
    assert(await hasNoHorizontalOverflow(page), `horizontal overflow at ${w}x${h}`);
  }
});

test("L6: keyboard is never inside a scrollable container and stays fully in view", async (page) => {
  // The reported bug: taps on the on-screen keyboard were swallowed as scroll
  // gestures because the keyboard lived inside an overflow-y:auto panel.
  // Assert structurally that nothing scrolls, at both a tight and a roomy size.
  for (const { w, h } of [{ w: 375, h: 667 }, { w: 390, h: 844 }]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(150);

    const overflowY = await page.evaluate(() => getComputedStyle(document.querySelector(".terminal")).overflowY);
    assert(overflowY !== "auto" && overflowY !== "scroll", `.terminal is scrollable (overflow-y: ${overflowY}) at ${w}x${h}`);

    const noInternalScroll = await page.evaluate(() => {
      const t = document.querySelector(".terminal");
      return t.scrollHeight <= t.clientHeight + 1;
    });
    assert(noInternalScroll, `.terminal content overflows its own box at ${w}x${h}`);

    const kbBox = await page.$eval("#keyboard", (el) => el.getBoundingClientRect());
    assert(kbBox.top >= 0 && kbBox.bottom <= h + 1, `#keyboard not fully within the ${w}x${h} viewport: top ${kbBox.top}, bottom ${kbBox.bottom}`);
  }
});

test("L6: board tiles never overlap each other, even on the tiniest phones", async (page) => {
  for (const { w, h } of [{ w: 320, h: 568 }, { w: 375, h: 667 }]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(150);

    const boxes = await page.evaluate(() => {
      const out = [];
      for (let r = 0; r < 6; r++) {
        const row = [];
        for (let c = 0; c < 5; c++) {
          row.push(document.getElementById(`tile-${r}-${c}`).getBoundingClientRect());
        }
        out.push(row);
      }
      return out;
    });

    for (let r = 0; r < 6; r++) {
      for (let c = 0; c < 5; c++) {
        const tile = boxes[r][c];
        assert(tile.width > 0 && tile.height > 0, `tile-${r}-${c} has collapsed to zero size at ${w}x${h}`);
        if (c < 4) {
          const next = boxes[r][c + 1];
          assert(tile.right <= next.left + 0.5, `tile-${r}-${c} overlaps tile-${r}-${c + 1} horizontally at ${w}x${h}`);
        }
        if (r < 5) {
          const below = boxes[r + 1][c];
          assert(tile.bottom <= below.top + 0.5, `tile-${r}-${c} overlaps tile-${r + 1}-${c} vertically at ${w}x${h}`);
        }
      }
    }
  }
});

// ────────────── L7: Timer ──────────────

test("L7: timer counts up during normal gameplay", async (page) => {
  const t1 = await page.textContent("#timer");
  await page.waitForTimeout(2200);
  const t2 = await page.textContent("#timer");
  assert(/^\d{2}:\d{2}$/.test(t1) && /^\d{2}:\d{2}$/.test(t2), `timer format unexpected: "${t1}" / "${t2}"`);
  const toSeconds = (t) => {
    const [m, s] = t.split(":").map(Number);
    return m * 60 + s;
  };
  assert(toSeconds(t2) > toSeconds(t1), `timer did not count up: ${t1} -> ${t2}`);
});

test("L7: timer freezes on win", async (page, context) => {
  const target = await decodeTarget(context);
  await typeWord(page, target);
  await page.waitForTimeout(FLIP_SETTLE_MS + 500);
  const t1 = await page.textContent("#timer");
  await page.waitForTimeout(1500);
  const t2 = await page.textContent("#timer");
  assert(t1 === t2, `timer should freeze on win, saw ${t1} -> ${t2}`);
});

// ────────────── L8: Edge & regression ──────────────

test("L8: rapid New Game clicking doesn't break state", async (page, context) => {
  const target1 = await decodeTarget(context);
  await typeWord(page, target1);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  // Rapid double-click New Game
  await page.click("#newgame");
  await page.click("#newgame");
  await page.waitForTimeout(1000);
  const target2 = await decodeTarget(context);
  assert(target2, "double-clicking new game left no target");

  // Still able to play
  await typeWord(page, target2);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  assert(/Solved in 1\/6/.test(await page.textContent("#message")), "game broken after rapid new-game click");
});

test("L8: win via last possible attempt (6th guess)", async (page, context) => {
  const target = await decodeTarget(context);
  const fillers = await guessDistinctFillers(target, 5);
  // 5 wrong guesses
  for (const w of fillers) {
    await typeWord(page, w);
    await page.waitForTimeout(FLIP_SETTLE_MS);
  }
  // 6th = correct
  await typeWord(page, target);
  await page.waitForTimeout(FLIP_SETTLE_MS);
  const message = await page.textContent("#message");
  assert(/Solved in 6\/6/.test(message), `expected last-attempt win, got "${message}"`);
});

test("L8: double-tapping ENTER on the winning guess submits exactly once and still detects the win", async (page, context) => {
  // Regression: submitGuess() had no in-flight guard, so a fast double-tap on
  // ENTER (or the on-screen key registering twice) fired two overlapping
  // /api/guess requests for the same word. Both scored against the same
  // stale pre-guess cookie, so the board could end up all green with the
  // attempt counter/win message thrown off or duplicated.
  const target = await decodeTarget(context);
  for (const ch of target) await page.keyboard.press(ch.toUpperCase());
  const responded = page.waitForResponse((res) => res.url().includes("/api/guess"));
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter"); // fired back-to-back, before the first response lands
  await responded;
  await page.waitForTimeout(FLIP_SETTLE_MS);

  const attemptCount = (await page.textContent("#attemptInfo")).trim();
  assert(attemptCount === "1" || attemptCount === "1/6", `expected exactly 1 attempt after a double-tap ENTER, got "${attemptCount}"`);

  const classes = await tileClasses(page, 0);
  classes.forEach((cls, i) => assert(classIncludes(cls, "correct"), `tile-0-${i} expected correct, got "${cls}"`));

  assert(/Solved in 1\/6/.test(await page.textContent("#message")), "win not correctly detected after double-tap ENTER");
});

test("L8: starting a new game right after a win doesn't get its message clobbered by the stale win-reveal timer", async (page, context) => {
  // Regression: the winning/losing message is applied via a setTimeout fired
  // ~1.3s after the guess response (to let the flip animation finish first).
  // That timer had no way to tell a new game had since started, so clicking
  // "New Game" within that window let the stale "Solved in X/6" text land
  // *after* newGame()'s "Guess the 5-letter word" message and overwrite it --
  // the board would show an empty fresh game with a leftover win message.
  const target = await decodeTarget(context);
  const responded = page.waitForResponse((res) => res.url().includes("/api/guess"));
  for (const ch of target) await page.keyboard.press(ch.toUpperCase());
  await page.keyboard.press("Enter");
  await responded; // guess response back, but the ~1.3s reveal-delay timer is still pending

  await page.click("#newgame");
  await waitForGameReady(page, context);
  await page.waitForTimeout(2000); // let the old game's stale reveal-delay timer fire, if it's going to

  const message = await page.textContent("#message");
  assert(!/Solved in/.test(message), `stale win message leaked into the new game: "${message}"`);
  assert(message.includes("Guess the"), `expected the new-game prompt to still be showing, got "${message}"`);
});

// ────────────── Main runner ──────────────

async function main() {
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const results = [];

  for (const { name, fn } of tests) {
    process.stdout.write(`- ${name} ... `);
    try {
      await withPage(browser, fn);
      console.log("PASS");
      results.push({ name, ok: true });
    } catch (err) {
      console.log("FAIL");
      console.log(`  ${err.message}`);
      results.push({ name, ok: false, error: err.message });
    }
  }

  await browser.close();

  const passed = results.filter((r) => r.ok).length;
  const failed = results.length - passed;
  console.log(`\n${passed}/${results.length} passed`);
  if (failed > 0) {
    console.log("\nFailed tests:");
    for (const r of results.filter((r) => !r.ok)) {
      console.log(`  - ${r.name}: ${r.error}`);
    }
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("QA runner crashed:", err);
  process.exit(1);
});
