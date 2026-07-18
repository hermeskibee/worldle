# 🎯 WORDLE — Task Tracker

> Live: https://worldle-eight.vercel.app
> DNS: https://wordle.mindster.space
> Repo: hermeskibee/worldle (private)

---

## 🔴 P1 — Bugs (krytyczne)

- [x] **Double-tap zoom** — szybkie 2x kliknięcie na klawiaturę przybliża stronę. Fix: `touch-action: manipulation` na body + meta viewport (`maximum-scale=1, user-scalable=no`).
- [x] **Biała pusta sekcja na dole** — layout ma pustą białą przestrzeń pod grą. Fix: `html` background dopasowany do gradientu + `overscroll-behavior: none`.
- [x] **Winning bug** — root cause: przycisk "New Game" (i klawisze) zatrzymywały fokus po kliknięciu, więc kolejny fizyczny Enter wywoływał natywny click na starym przycisku równolegle z submitGuess(), co psuło stan gry. Fix: `mousedown` → `preventDefault()` na wszystkich przyciskach klawiatury i #newgame.
- [x] **Nieaktywne literki** — literki oznaczone jako "absent" dostają teraz `disabled = true` na przycisku (nieklikalne). Shake/komunikat nie zaimplementowany — nie było w bieżącym zakresie zgłoszenia.

## 🟡 P2 — Features (ważne)

- [ ] **Lepszy system hintów** — hint words klikalne (auto-wypełnienie i submit), checkbox "pin hints" (małe ikonki sticky na stałe).
- [ ] **Footer** — "Created by Mindster – Moca Mind" na dole strony.
- [ ] **QA loop** — po każdej zmianie odpalić Playwright QA suite. Jeśli testy padną — loop fix → test → fix → test aż wszystko przejdzie.

## 🟢 P3 — Ulepszenia

- (wolne miejsce — dodać jak P1 i P2 zamknięte)

---

## Instrukcja dla Claude Code

1. Zajmuj się taskami od góry (P1 → P2 → P3).
2. Po każdej zmianie → odpal `node scripts/qa-test.mjs`.
3. Jeśli QA pada → fixuj i loopuj aż przejdzie.
4. Jak task zrobiony → odznacz checkbox (`- [x]`), pushnij, i dopiero raportuj.
5. Jak utkniesz → zapisz w tasku "🔒 BLOCKED: [powód]" i czekaj na instrukcje.
