# Księgi Wieczyste PDF Generator

Automates the generation of PDF files from the Polish land registry viewer (Elektroniczna Księga Wieczysta).

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
python ekw_downloader.py WA2M/00436586/7
```

This will generate a PDF file containing all 5 sections of the land registry entry.

## How it works

1. Opens the land registry viewer in a headless browser
2. Searches for the specified entry (fills in court code, number, and control digit)
3. Clicks "Przeglądanie aktualnej treści KW" button
4. Downloads all 5 sections (Dział I-O, I-Sp, II, III, IV)
5. Combines everything into a single PDF file

## Output

The generated PDF will be saved as `{entry_number}.pdf` in the current directory (e.g., `WA2M_00436586_7.pdf`).
