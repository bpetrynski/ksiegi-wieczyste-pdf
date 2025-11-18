#!/usr/bin/env python3
"""
Elektroniczna Księga Wieczysta PDF Generator

Automates the generation of PDF files from the Polish land registry viewer.
"""

import sys
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PyPDF2 import PdfMerger
from datetime import datetime


class EKWDownloader:
    """Downloader for Polish land registry (Elektroniczna Księga Wieczysta)"""

    BASE_URL = "https://przegladarka-ekw.ms.gov.pl/"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.screenshots_dir = Path("screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)

    def validate_entry_number(self, entry_number: str) -> bool:
        """Validate the format of the entry number (e.g., WA2M/00436586/7)"""
        pattern = r'^[A-Z0-9]+/\d+/\d+$'
        return bool(re.match(pattern, entry_number))

    def parse_entry_number(self, entry_number: str) -> dict:
        """
        Parse entry number into components.
        Format: WA2M/00436586/7
        - Court code: WA2M
        - Number: 00436586
        - Control digit: 7
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
            entry_number: The entry number (e.g., WA2M/00436586/7)
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

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )
            page = context.new_page()

            try:
                # Navigate to the main page
                print(f"Navigating to {self.BASE_URL}...")
                page.goto(self.BASE_URL, wait_until='networkidle', timeout=30000)

                # Wait for TSPD (Traffic Server Protection Detection) to complete
                # The site uses anti-bot protection that needs time to load
                print("Waiting for anti-bot protection to complete...")
                time.sleep(5)

                # Wait for the actual form content to appear
                # Look for any input field or form element to confirm page is loaded
                try:
                    page.wait_for_selector('input', timeout=15000)
                    print("Form elements detected, page loaded successfully")
                except PlaywrightTimeoutError:
                    print("Warning: No input fields detected after waiting. Continuing anyway...")

                # Additional wait for JavaScript to fully execute
                time.sleep(2)

                # Parse the entry number into 3 parts
                # Format: WA2M/00436586/7 -> court_code, number, control
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

                # Collect all pages/sections
                pdf_pages = []

                # The 5 tabs we need to capture:
                # Tabs are submit buttons with value="Dział I-O", etc.
                tab_names = [
                    "Dział I-O",
                    "Dział I-Sp",
                    "Dział II",
                    "Dział III",
                    "Dział IV"
                ]

                print(f"Capturing {len(tab_names)} tabs...")

                # Capture each tab by clicking its submit button
                for idx, tab_name in enumerate(tab_names):
                    try:
                        clean_name = tab_name.replace('/', '_').replace(' ', '_')
                        print(f"  [{idx + 1}/{len(tab_names)}] Looking for tab: {tab_name}...")

                        # Find the submit button for this tab
                        # The tabs are <input type="submit" value="Dział I-O"> etc.
                        tab_button = None

                        # Use CSS selector to find input[type="submit"] with specific value
                        selector = f'input[type="submit"][value="{tab_name}"]'

                        try:
                            tab_button = page.wait_for_selector(selector, timeout=3000)
                        except PlaywrightTimeoutError:
                            print(f"      ✗ Could not find submit button for: {tab_name}")
                            page.screenshot(path=str(self.screenshots_dir / f"debug_missing_{clean_name}.png"))
                            continue

                        if not tab_button:
                            print(f"      ✗ Could not find tab: {tab_name}")
                            continue

                        print(f"      Found submit button, clicking...")

                        # Click the submit button
                        tab_button.click()
                        page.wait_for_load_state('networkidle')
                        time.sleep(2)

                        # Capture screenshot of this tab (full page to get all content)
                        screenshot_path = self.screenshots_dir / f"page_{idx+1:02d}_{clean_name}.png"
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        pdf_pages.append(screenshot_path)
                        print(f"      ✓ Captured: {screenshot_path.name}")

                    except Exception as e:
                        print(f"      ✗ Error capturing tab '{tab_name}': {e}")
                        # Save error screenshot
                        try:
                            page.screenshot(path=str(self.screenshots_dir / f"error_tab_{clean_name}.png"))
                        except:
                            pass
                        continue

                if not pdf_pages:
                    print("\nWarning: No tabs captured! Taking fallback screenshot...")
                    page.screenshot(path=str(self.screenshots_dir / "debug_no_tabs.png"))
                    main_screenshot = self.screenshots_dir / f"page_00_single.png"
                    page.screenshot(path=str(main_screenshot), full_page=True)
                    pdf_pages.append(main_screenshot)

                # Generate the final PDF
                print(f"\nGenerating PDF with {len(pdf_pages)} pages...")
                self._create_pdf_from_images(pdf_pages, output_file)

                print(f"✓ PDF generated successfully: {output_file}")
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

    def _create_pdf_from_images(self, image_paths: list, output_file: str):
        """Convert a list of images to a PDF file, splitting tall images across multiple A4 pages"""
        from PIL import Image
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader

        c = canvas.Canvas(output_file, pagesize=A4)
        a4_width, a4_height = A4

        for img_path in image_paths:
            if not img_path.exists():
                continue

            img = Image.open(img_path)
            img_width, img_height = img.size

            # Calculate scaling to fit to A4 width
            width_ratio = a4_width / img_width
            scaled_width = a4_width
            scaled_height = img_height * width_ratio

            # If the scaled image fits on one A4 page, just add it
            if scaled_height <= a4_height:
                c.setPageSize(A4)
                x = 0
                # Align to top of page
                y = a4_height - scaled_height
                c.drawImage(str(img_path), x, y, width=scaled_width, height=scaled_height)
                c.showPage()
            else:
                # Image is too tall - split it across multiple A4 pages
                # Add overlap between pages (approximately 30% of one line of text)
                overlap_points = 6  # Overlap in PDF points (30% of ~20pt)
                overlap_in_original = overlap_points / width_ratio  # Convert to original image pixels

                # Calculate how many A4 pages we need
                num_pages = int((scaled_height + a4_height - 1) / a4_height)  # Ceiling division

                print(f"      Splitting {img_path.name} across {num_pages} pages (height: {scaled_height:.0f}pt)")

                # For each page, we need to crop a portion of the original image
                for page_num in range(num_pages):
                    c.setPageSize(A4)

                    # Calculate which vertical slice of the original image to use
                    # In original image coordinates
                    slice_height_in_original = a4_height / width_ratio

                    # Apply overlap: start a bit earlier on pages after the first
                    if page_num > 0:
                        y_start_in_original = page_num * slice_height_in_original - overlap_in_original
                    else:
                        y_start_in_original = 0

                    y_end_in_original = min((page_num + 1) * slice_height_in_original, img_height)

                    actual_slice_height = y_end_in_original - y_start_in_original

                    # Crop the image slice
                    img_slice = img.crop((0, int(y_start_in_original), img_width, int(y_end_in_original)))

                    # Save temporary slice
                    temp_slice_path = img_path.parent / f"temp_slice_{page_num}.png"
                    img_slice.save(temp_slice_path)

                    # Calculate dimensions for this slice when scaled
                    slice_scaled_height = actual_slice_height * width_ratio

                    # Draw the slice at the top of the page
                    x = 0
                    y = a4_height - slice_scaled_height

                    c.drawImage(str(temp_slice_path), x, y, width=scaled_width, height=slice_scaled_height)
                    c.showPage()

                    # Clean up temp file
                    temp_slice_path.unlink()

        c.save()
        print(f"PDF saved: {output_file}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python ekw_downloader.py <entry_number> [--show-browser]")
        print("Example: python ekw_downloader.py WA2M/00436586/7")
        sys.exit(1)

    entry_number = sys.argv[1]
    headless = '--show-browser' not in sys.argv

    downloader = EKWDownloader(headless=headless)

    try:
        output_file = downloader.download(entry_number)
        print(f"\n✓ Success! PDF generated: {output_file}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
