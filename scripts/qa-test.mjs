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
    const attemptCount = await page.textContent("#attemptCount").catch(() => null);
    if (target && attemptCount != null && attemptCount.trim() === "0") return;
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

test("page loads with full board, keyboard, and no console errors", async (page) => {
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

test("full win: guessing the target registers a win with correct tile colors", async (page, context) => {
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

test("new game after a win resets state and can be won again", async (page, context) => {
  const target1 = await decodeTarget(context);
  await typeWord(page, target1);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  await page.click("#newgame");
  await waitForGameReady(page, context);
  assert((await page.textContent("#attemptCount")).trim() === "0", "attempt count did not reset");
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

test("full loss: 6 wrong guesses end the game, reveal the word, and freeze the timer", async (page, context) => {
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

test("new game after a loss resets tiles and scores the next game against the new target", async (page, context) => {
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

test("hint level 1 reveals a correct letter without breaking layout", async (page, context) => {
  await page.click("#hintBtn");
  await page.waitForTimeout(150);
  const options = await page.$$(".modal-option");
  assert(options.length === 3, `expected 3 hint options, got ${options.length}`);
  await options[0].click();
  await page.waitForTimeout(150);
  await confirmHint(page);
  await page.waitForTimeout(150); // let the DOM update after the response

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

test("hint level 2 shows a handful of candidate words without breaking layout", async (page, context) => {
  await page.click("#hintBtn");
  await page.waitForTimeout(150);
  const options = await page.$$(".modal-option");
  await options[1].click();
  await page.waitForTimeout(150);
  await confirmHint(page);
  await page.waitForTimeout(150); // let the DOM update after the response

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

test("hint level 3 lists all remaining candidates without breaking layout", async (page, context) => {
  const target = await decodeTarget(context);
  await page.click("#hintBtn");
  await page.waitForTimeout(150);
  const options = await page.$$(".modal-option");
  await options[2].click();
  await page.waitForTimeout(150);
  await confirmHint(page);
  await page.waitForTimeout(150); // let the DOM update after the response

  assert(await hasNoHorizontalOverflow(page), "layout overflowed horizontally after hint level 3 (2489 words)");
  const heading = (await page.textContent("#hintModal h2")).trim();
  assert(/All remaining words \(\d+\)/.test(heading), `unexpected level-3 heading: "${heading}"`);

  const modalBox = await page.$eval("#hintModal", (el) => {
    const r = el.getBoundingClientRect();
    return { width: r.width, height: r.height, viewportH: window.innerHeight };
  });
  assert(modalBox.height <= modalBox.viewportH, "hint modal taller than viewport -- word list is not scroll-contained");

  const chips = await page.$$(".word-chip");
  const chipTexts = new Set();
  for (const chip of chips) chipTexts.add((await chip.textContent()).trim());
  assert(chipTexts.has(target.toUpperCase()), "target word missing from the exhaustive candidate list (with zero guesses made, it must match)");

  assert(await page.isVisible("#board"), "board hidden/broken after hint level 3");
  await page.click(".modal-close");
});

test("invalid input is rejected without consuming an attempt", async (page) => {
  await page.keyboard.press("A");
  await page.keyboard.press("B");
  await page.keyboard.press("C");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  assert((await page.textContent("#message")).includes("Not enough letters"), "short guess was not rejected");
  assert((await page.textContent("#attemptCount")).trim() === "0", "attempt count changed on rejected short guess");

  // clear the partial guess, then try a real 5-letter word that is not in the word list
  await page.keyboard.press("Backspace");
  await page.keyboard.press("Backspace");
  await page.keyboard.press("Backspace");
  await typeWord(page, "ZZZZQ");
  await page.waitForTimeout(300);
  const msg = await page.textContent("#message");
  assert(/isn't in the word list/.test(msg), `expected word-list rejection, got "${msg}"`);
  assert((await page.textContent("#attemptCount")).trim() === "0", "attempt count changed on invalid word");
});

test("mobile zoom-gesture guards are present (viewport + touch-action)", async (page) => {
  const viewport = await page.getAttribute('meta[name="viewport"]', "content");
  assert(/maximum-scale=1/.test(viewport), `viewport missing maximum-scale=1: "${viewport}"`);
  assert(/user-scalable=no/.test(viewport), `viewport missing user-scalable=no: "${viewport}"`);

  const bodyTouchAction = await page.evaluate(() => getComputedStyle(document.body).touchAction);
  assert(bodyTouchAction === "manipulation", `body touch-action expected "manipulation", got "${bodyTouchAction}"`);

  const htmlOverscroll = await page.evaluate(() => getComputedStyle(document.documentElement).overscrollBehaviorY);
  assert(htmlOverscroll === "none", `html overscroll-behavior expected "none", got "${htmlOverscroll}"`);
});

test("no white gap below game content (html background matches page theme)", async (page) => {
  const htmlBg = await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor);
  assert(htmlBg !== "rgba(0, 0, 0, 0)" && htmlBg !== "rgb(255, 255, 255)", `html background looks unset/white: "${htmlBg}"`);
});

test("page fits within the viewport on small phones (iPhone SE, no overflow scroll)", async (page) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.waitForTimeout(150); // let the resize-driven reflow settle
  const metrics = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
  }));
  assert(
    metrics.scrollHeight <= metrics.clientHeight + 1,
    `page overflows the viewport on a 375x667 screen: scrollHeight ${metrics.scrollHeight} > clientHeight ${metrics.clientHeight}`
  );
  for (const sel of ["#board", "#keyboard", "#newgame", ".site-footer"]) {
    assert(await page.isVisible(sel), `${sel} not visible on a 375x667 screen`);
  }
});

test("ruled-out (absent) keyboard letters become disabled and unclickable", async (page, context) => {
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

test("new game after a win doesn't double-submit via a focus-stolen Enter keypress", async (page, context) => {
  const target1 = await decodeTarget(context);
  await typeWord(page, target1);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  await page.click("#newgame");
  await waitForGameReady(page, context);

  const target2 = await decodeTarget(context);
  assert(target2, "no target after new game");
  await typeWord(page, target2);
  await page.waitForTimeout(FLIP_SETTLE_MS);

  const attempts = await page.evaluate(() => attempts);
  assert(attempts.length === 1, `expected exactly 1 attempt recorded, got ${attempts.length}`);
  assert(attempts[0].word === target2, `attempt word corrupted: expected "${target2}", got "${attempts[0].word}"`);
  assert(/Solved in 1\/6/.test(await page.textContent("#message")), "win message missing/wrong after new-game + win");
});

test("timer counts up while the game is in progress", async (page) => {
  const t1 = await page.textContent("#timer");
  await page.waitForTimeout(2200);
  const t2 = await page.textContent("#timer");
  assert(/^\d{2}:\d{2}$/.test(t1) && /^\d{2}:\d{2}$/.test(t2), `timer format unexpected: "${t1}" / "${t2}"`);
  const toSeconds = (t) => {
    const [m, s] = t.split(":").map(Number);
    return m * 60 + s;
  };
  assert(toSeconds(t2) > toSeconds(t1), `timer did not advance: ${t1} -> ${t2}`);
});

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
