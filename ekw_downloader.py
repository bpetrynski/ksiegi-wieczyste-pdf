#!/usr/bin/env python3
"""
Elektroniczna Księga Wieczysta PDF Generator

Automates the generation of PDF files from the Polish land registry viewer.
"""

import sys
import re
import time
import csv
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth
from PyPDF2 import PdfMerger

# Error logging (used in batch mode)
LOG_FILE = Path("ekw_errors.log")
logger = logging.getLogger(__name__)


class EKWDownloader:
    """Downloader for Polish land registry (Elektroniczna Księga Wieczysta)"""

    BASE_URL = "https://przegladarka-ekw.ms.gov.pl/"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.screenshots_dir = Path("screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)

    def validate_entry_number(self, entry_number: str) -> bool:
        """Validate the format of the entry number (e.g., KR1P/00012345/4)"""
        pattern = r'^[A-Z0-9]+/\d+/\d+$'
        return bool(re.match(pattern, entry_number))

    def parse_entry_number(self, entry_number: str) -> dict:
        """
        Parse entry number into components.
        Format: KR1P/00012345/4
        - Court code: KR1P
        - Number: 00012345
        - Control digit: 4
        """
        parts = entry_number.split('/')
        return {
            'court_code': parts[0],
            'number': parts[1],
            'control': parts[2],
            'full': entry_number
        }

    def download(self, entry_number: str, output_file: str = None) -> str:
        """
        Download all pages of a land registry entry and generate a PDF.

        Args:
            entry_number: The entry number (e.g., KR1P/00012345/4)
            output_file: Optional output filename (defaults to {entry_number}.pdf)

        Returns:
            Path to the generated PDF file
        """
        if not self.validate_entry_number(entry_number):
            raise ValueError(f"Invalid entry number format: {entry_number}")

        if output_file is None:
            # Replace slashes with underscores for filename
            safe_name = entry_number.replace('/', '_')
            output_file = f"{safe_name}.pdf"

        print(f"Starting download for entry: {entry_number}")

        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
        ]
        if self.headless:
            launch_args.append('--headless=new')  # Chrome's less-detectable headless

        playwright_cm = Stealth().use_sync(sync_playwright()) if self.headless else sync_playwright()
        with playwright_cm as p:
            browser = p.chromium.launch(headless=self.headless, args=launch_args)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                ignore_https_errors=True,
                locale='pl-PL',
            )
            page = context.new_page()
            if not self.headless:
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            try:
                # Navigate to the main page (domcontentloaded so JS can run before we check)
                print(f"Navigating to {self.BASE_URL}...")
                page.goto(self.BASE_URL, wait_until='domcontentloaded', timeout=30000)
                time.sleep(2)

                # Wait for TSPD (Traffic Server Protection Detection) to complete
                # The site uses anti-bot protection that needs time to load
                print("Waiting for anti-bot protection to complete (up to 55s)...")
                try:
                    page.wait_for_selector('input[type="text"]', timeout=55000)
                    print("Form elements detected, page loaded successfully")
                except PlaywrightTimeoutError:
                    print("Warning: No input fields detected after 60s. Try with --show-browser if blocked.")
                time.sleep(2)

                # Parse the entry number into 3 parts
                # Format: KR1P/00012345/4 -> court_code, number, control
                entry_parts = self.parse_entry_number(entry_number)
                print(f"Entry parts: Court={entry_parts['court_code']}, Number={entry_parts['number']}, Control={entry_parts['control']}")

                # Look for the search input fields (3 separate fields)
                print("Looking for search form with 3 input fields...")

                # Debug: Print page HTML to understand structure
                page_html = page.content()
                with open(self.screenshots_dir / "page_debug.html", "w", encoding="utf-8") as f:
                    f.write(page_html)
                print(f"Page HTML saved to {self.screenshots_dir / 'page_debug.html'}")

                # Try multiple selector strategies
                strategies = [
                    ('input[type="text"]', 'text inputs'),
                    ('input', 'all inputs'),
                    ('input:visible', 'visible inputs'),
                    ('input:not([type="hidden"])', 'non-hidden inputs'),
                    ('form input', 'form inputs'),
                ]

                input_fields = []
                for selector, description in strategies:
                    try:
                        fields = page.query_selector_all(selector)
                        print(f"Strategy '{description}' ({selector}): found {len(fields)} fields")
                        if len(fields) >= 3:
                            input_fields = fields
                            print(f"Using strategy: {description}")
                            break
                    except Exception as e:
                        print(f"Strategy '{description}' failed: {e}")

                # Debug: Print attributes of found inputs
                if input_fields:
                    for i, field in enumerate(input_fields[:5]):  # Show first 5
                        attrs = page.evaluate('(el) => Array.from(el.attributes).map(a => `${a.name}="${a.value}"`).join(" ")', field)
                        print(f"Input {i}: <input {attrs}>")

                print(f"\nFound {len(input_fields)} input fields total")

                if len(input_fields) < 3:
                    page.screenshot(path=str(self.screenshots_dir / "error_no_inputs.png"))
                    raise Exception(f"Expected at least 3 input fields, found {len(input_fields)}. Screenshot saved. Check page_debug.html for details.")

                # Fill the three fields with the parsed entry number
                # Typically: [court_code, number, control_digit]
                print(f"\nFilling field 1 with: {entry_parts['court_code']}")
                input_fields[0].fill(entry_parts['court_code'])
                time.sleep(0.5)

                print(f"Filling field 2 with: {entry_parts['number']}")
                input_fields[1].fill(entry_parts['number'])
                time.sleep(0.5)

                print(f"Filling field 3 with: {entry_parts['control']}")
                input_fields[2].fill(entry_parts['control'])
                time.sleep(0.5)

                print("All fields filled successfully!\n")

                # Save screenshot of filled form
                page.screenshot(path=str(self.screenshots_dir / "form_filled.png"))
                print("Screenshot saved: form_filled.png")

                # Find and click the search button
                search_button = None
                button_selectors = [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("Wyszukaj")',
                    'button:has-text("Szukaj")',
                    'a:has-text("Wyszukaj")',
                ]

                for selector in button_selectors:
                    try:
                        search_button = page.wait_for_selector(selector, timeout=5000)
                        if search_button:
                            print(f"Found search button with selector: {selector}")
                            break
                    except PlaywrightTimeoutError:
                        continue

                if not search_button:
                    page.screenshot(path=str(self.screenshots_dir / "error_no_button.png"))
                    raise Exception("Could not find search button. Screenshot saved.")

                # Click search and wait for results
                print("Clicking search button...")
                search_button.click()
                page.wait_for_load_state('networkidle')
                time.sleep(2)

                # Now we should be on the results page with multiple action buttons
                # Look for "Przeglądanie aktualnej treści KW" button
                print("Waiting for results page with action buttons...")

                # Save screenshot of results page for debugging
                page.screenshot(path=str(self.screenshots_dir / "results_page.png"))
                print("Screenshot saved: results_page.png")

                # Find and click "Przeglądanie aktualnej treści KW" button
                print("Looking for 'Przeglądanie aktualnej treści KW' button...")

                viewing_button = None
                viewing_button_selectors = [
                    'button:has-text("Przeglądanie aktualnej treści KW")',
                    'a:has-text("Przeglądanie aktualnej treści KW")',
                    'input[value*="Przeglądanie aktualnej treści KW"]',
                    '*:has-text("Przeglądanie aktualnej treści KW")',  # Any element
                ]

                for selector in viewing_button_selectors:
                    try:
                        viewing_button = page.wait_for_selector(selector, timeout=5000)
                        if viewing_button:
                            print(f"Found viewing button with selector: {selector}")
                            break
                    except PlaywrightTimeoutError:
                        continue

                if not viewing_button:
                    page.screenshot(path=str(self.screenshots_dir / "error_no_viewing_button.png"))
                    raise Exception("Could not find 'Przeglądanie aktualnej treści KW' button. Screenshot saved.")

                # Click the viewing button
                print("Clicking 'Przeglądanie aktualnej treści KW' button...")
                viewing_button.click()
                page.wait_for_load_state('networkidle')
                time.sleep(3)

                print("Now on the land registry content page!\n")

                # Collect PDF for each section (browser print = copyable text)
                tab_pdf_paths = []

                # The 5 tabs we need to capture:
                tab_names = [
                    "Dział I-O",
                    "Dział I-Sp",
                    "Dział II",
                    "Dział III",
                    "Dział IV"
                ]

                print(f"Capturing {len(tab_names)} tabs as PDF (copyable text)...")

                for idx, tab_name in enumerate(tab_names):
                    try:
                        clean_name = tab_name.replace('/', '_').replace(' ', '_')
                        print(f"  [{idx + 1}/{len(tab_names)}] Tab: {tab_name}...")

                        selector = f'input[type="submit"][value="{tab_name}"]'
                        try:
                            tab_button = page.wait_for_selector(selector, timeout=3000)
                        except PlaywrightTimeoutError:
                            print(f"      ✗ Could not find submit button for: {tab_name}")
                            page.screenshot(path=str(self.screenshots_dir / f"debug_missing_{clean_name}.png"))
                            continue

                        if not tab_button:
                            continue

                        tab_button.click()
                        page.wait_for_load_state('networkidle')
                        time.sleep(2)

                        # Export as PDF (Chromium uses real DOM text = copyable)
                        tab_pdf = self.screenshots_dir / f"tab_{idx+1:02d}_{clean_name}.pdf"
                        page.pdf(
                            path=str(tab_pdf),
                            print_background=True,
                            margin={"top": "0.5cm", "bottom": "0.5cm", "left": "0.5cm", "right": "0.5cm"},
                        )
                        tab_pdf_paths.append(tab_pdf)
                        print(f"      ✓ PDF: {tab_pdf.name}")

                    except Exception as e:
                        print(f"      ✗ Error capturing tab '{tab_name}': {e}")
                        try:
                            page.screenshot(path=str(self.screenshots_dir / f"error_tab_{clean_name}.png"))
                        except Exception:
                            pass
                        continue

                if not tab_pdf_paths:
                    raise Exception("No tabs captured. Check screenshots/ for errors.")

                # Merge all section PDFs into one
                print(f"\nMerging {len(tab_pdf_paths)} PDFs...")
                merger = PdfMerger()
                for p in tab_pdf_paths:
                    merger.append(str(p))
                merger.write(output_file)
                merger.close()

                # Clean up temporary tab PDFs
                for p in tab_pdf_paths:
                    try:
                        p.unlink()
                    except Exception:
                        pass

                print(f"✓ PDF generated successfully (copyable text): {output_file}")
                return output_file

            except Exception as e:
                print(f"Error during download: {e}")
                # Save error screenshot
                try:
                    page.screenshot(path=str(self.screenshots_dir / "error_final.png"))
                    print(f"Error screenshot saved to: {self.screenshots_dir / 'error_final.png'}")
                except:
                    pass
                raise

            finally:
                browser.close()


def _setup_error_logging():
    """Configure logger to write errors to file and stderr."""
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.ERROR)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.ERROR)
        ch.setFormatter(fmt)
        logger.addHandler(ch)


def run_batch(csv_path: str) -> None:
    """
    Process all KW from a CSV file (column 'KW'). Runs in headless mode.
    Logs errors to ekw_errors.log and stderr; continues on failure.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        logger.error("CSV file not found: %s", csv_path)
        sys.exit(1)

    _setup_error_logging()

    entries = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "KW" not in (reader.fieldnames or []):
            logger.error("CSV must have a 'KW' column")
            sys.exit(1)
        for row in reader:
            kw = (row.get("KW") or "").strip()
            if kw and kw.upper() != "KW":
                entries.append(kw)

    if not entries:
        logger.error("No KW entries found in %s", csv_path)
        sys.exit(1)

    downloader = EKWDownloader(headless=True)
    ok = 0
    failed = []

    print(f"Batch: {len(entries)} entries from {csv_path} (headless)")
    print(f"Errors will be logged to {LOG_FILE}\n")

    for i, entry_number in enumerate(entries, 1):
        try:
            downloader.download(entry_number)
            ok += 1
            print(f"  [{i}/{len(entries)}] {entry_number} ✓")
        except Exception as e:
            failed.append((entry_number, str(e)))
            logger.error("KW %s: %s", entry_number, e)
            print(f"  [{i}/{len(entries)}] {entry_number} ✗ {e}")

    print(f"\nDone: {ok} OK, {len(failed)} failed")
    if failed:
        print(f"Failed: {[e[0] for e in failed]}")
        print(f"See {LOG_FILE} for details.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python ekw_downloader.py <entry_number|input.csv> [--show-browser]")
        print("  Single: python ekw_downloader.py KR1P/00012345/4")
        print("  Batch:  python ekw_downloader.py input.csv  (headless, errors in ekw_errors.log)")
        sys.exit(1)

    arg = sys.argv[1]
    headless = "--show-browser" not in sys.argv

    if arg.endswith(".csv"):
        run_batch(arg)
        return

    downloader = EKWDownloader(headless=headless)
    try:
        output_file = downloader.download(arg)
        print(f"\n✓ Success! PDF generated: {output_file}")
    except Exception as e:
        _setup_error_logging()
        logger.error("KW %s: %s", arg, e)
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
