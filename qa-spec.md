# ✅ WORDLE — QA Spec (Playwright)

> Test suite: `scripts/qa-test.mjs`
> Base URL: `http://127.0.0.1:8811` (local) lub `https://worldle-eight.vercel.app`

---

## Testy krytyczne (muszą przejść)

### 1. Strona się ładuje
- [ ] `GET /` → 200
- [ ] Tytuł "WORDLE" widoczny
- [ ] Footer "Created by Mindster – Moca Mind" widoczny (footer)
- [ ] Siatka 5×6 widoczna
- [ ] Klawiatura wirtualna widoczna

### 2. Rozgrywka
- [ ] Nowa gra (`POST /api/new`) → 200, zwraca stan gry
- [ ] Zgadnięcie słowa (`POST /api/guess`) → 200, zwraca resultat
- [ ] 5-literowe słowo → zielone/wszystkie litery
- [ ] Niepoprawne słowo → szare literki
- [ ] Częściowo poprawne → żółte literki
- [ ] Po 6 błędnych próbach → game over
- [ ] Po odgadnięciu wszystkich 5 liter → ekran wygranej (congratulations)

### 3. Hinty
- [ ] `/api/hint` → zwraca hint
- [ ] Hint words są klikalne → kliknięcie wypełnia input i submittuje
- [ ] Pin checkbox działa → hint zostaje na stałe jako małe ikonki

### 4. Klawiatura i UI
- [ ] Kliknięcie literki na klawiaturze → wpisuje się w aktywny wiersz
- [ ] Po użyciu literki → znika / robi się disabled na klawiaturze
- [ ] Kliknięcie nieaktywnej literki → NIE wpisuje się, ekran shake + komunikat
- [ ] Double-tap na klawiaturę → NIE przybliża strony (touch-action)

### 5. Timer
- [ ] Timer odlicza od 10:00 do 0:00
- [ ] Po 0:00 → gra się kończy (game over)

### 6. Daily mode
- [ ] `/api/daily` → to samo słowo dla wszystkich tego dnia
- [ ] Po odgadnięciu daily → statystyki pokazują "streak: X"

---

## Uruchamianie

```bash
# Lokalnie (najpierw odpal serwer)
cd ~/projects/mocaminds/worldle
python3 -m api.index  # lub jak się uruchamia
node scripts/qa-test.mjs

# Na Vercel
BASE_URL=https://worldle-eight.vercel.app node scripts/qa-test.mjs
```

## QA Loop rule

> **Po KAŻDEJ zmianie w kodzie → odpalić Playwright QA suite.**
> Jeśli choć jeden test pada → NIE pushować.
> Fixować i loopować (`node scripts/qa-test.mjs`) aż wszystkie przejdą.
> Dopiero wtedy commit + push + raport.
