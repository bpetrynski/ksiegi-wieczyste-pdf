# Księgi Wieczyste PDF Generator (fork)

Automates the generation of PDF files from the Polish land registry viewer (Elektroniczna Księga Wieczysta – EKW).

---

## Zmiany w tym forku względem oryginału

- **PDF z kopiowalnym tekstem** – zamiast zrzutów ekranu używany jest eksport „drukuj do PDF” (Chromium), więc tekst w PDF można zaznaczać i kopiować.
- **Tryb wsadowy z CSV** – obsługa pliku CSV z kolumną `KW`; wszystkie wpisy są pobierane w jednym uruchomieniu (headless).
- **Logowanie błędów** – błędy zapisywane do `ekw_errors.log` i na stderr; przy błędzie skrypt przechodzi do kolejnego wpisu z CSV.
- **Headless z ochroną anty-bot** – integracja z **playwright-stealth** oraz tryb `--headless=new` Chromium, żeby headless działał mimo zabezpieczeń strony EKW (bez potrzeby `--show-browser`).
- **Uproszczone zależności** – usunięto reportlab i Pillow (nieużywane po przejściu na PDF z przeglądarki).

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

Skrypt ma **dwa tryby**, wybór zależy od pierwszego argumentu:

| Pierwszy argument | Tryb | Opis |
|-------------------|-----|-----|
| **Numer KW** (np. `KR1P/00012345/4`) | Pojedyncza księga | Pobiera jedną księgę, zapisuje jeden PDF. Domyślnie headless; z `--show-browser` otwiera okno przeglądarki. |
| **Ścieżka do pliku `.csv`** (np. `input.csv`) | Batch | Czyta z CSV kolumnę `KW`, pobiera po kolei wszystkie księgi (zawsze headless). Błędy do `ekw_errors.log`, przy błędzie przechodzi do kolejnego wpisu. |

**Pojedyncza księga:**
```bash
python ekw_downloader.py KR1P/00012345/4
python ekw_downloader.py KR1P/00012345/4 --show-browser   # opcjonalnie, jeśli headless jest blokowany
```

**Batch z CSV:**
```bash
python ekw_downloader.py input.csv
```

CSV musi mieć kolumnę **`KW`** z numerami ksiąg. Przykładowy plik: `input.example.csv`. Błędy trafiają do `ekw_errors.log` i na stderr.

## Format CSV

Nagłówek z kolumną `KW`, w wierszach numery ksiąg w formacie `KOD/ numer/cyfra_kontrolna`, np.:

```csv
Lokal,KW
1,KR1P/00012345/4
```

## Jak to działa

1. Otwiera przeglądarkę (headless lub z oknem przy `--show-browser`).
2. Wchodzi na stronę EKW i czeka na przejście ochrony anty-bot (stealth + nowy headless).
3. Wypełnia formularz (kod wydziału, numer KW, cyfra kontrolna) i klika „Wyszukaj”.
4. Klika „Przeglądanie aktualnej treści KW”.
5. Dla każdego działu (I-O, I-Sp, II, III, IV) eksportuje treść do PDF (tekst kopiowalny).
6. Łączy wszystkie PDF-y w jeden plik.

## Output

PDF zapisywany w bieżącym katalogu jako `{numer_KW}.pdf` (np. `KR1P_00012345_4.pdf`). Błędy batcha: `ekw_errors.log`.
