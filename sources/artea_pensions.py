#!/usr/bin/env python3
"""
Artea pension funds scraper.
Handles a clickable expandable fund selector and extracts key fund metrics.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Add parent directory to path so we can import base_scraper
sys.path.insert(0, str(Path(__file__).parent.parent))

from base_scraper import BaseScraper


class ArteaPensionsScraper(BaseScraper):
    """Scrapes Artea II pillar pension funds from the expandable selector."""

    URL = "https://www.artea.lt/lt/privatiems/pensija/ii-pakopos-pensija/artea-pensiju-turto-issaugojimo-fondas"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    EXCLUDED_FUNDS = {"Artea pensija 1954-1960 Index Plus"}
    FUND_SELECTOR_CANDIDATES = [
        ".custom-select-opener[role='combobox']",
        ".custom-select-opener",
        "[role='combobox']",
    ]

    def __init__(self):
        super().__init__("artea_pensions")
        self._playwright = None

    def get_url(self) -> str:
        return self.URL

    def setup_browser(self):
        """Use Cloudflare-friendlier browser settings for Artea."""
        print("Starting browser...")
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",  # Fixes issues in low-memory environments
                "--no-sandbox",  # Required in containers
                "--disable-gpu",
            ],
        )
        context = self.browser.new_context(
            user_agent=self.USER_AGENT,
            locale="lt-LT",
            timezone_id="Europe/Vilnius",
        )
        self.page = context.new_page()
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return self.page

    def cleanup_browser(self):
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()

    def dismiss_cookie_modal(self, page):
        """Dismiss OneTrust modal/panel that can block clicks."""
        # First pass: try common dismiss buttons
        selectors = [
            "button:has-text('Leisti visus')",
            "button:has-text('Allow All')",
            "#onetrust-accept-btn-handler",
            "button:has-text('Patvirt')",  # Patvirtinti...
            "#onetrust-reject-all-handler",
            "button:has-text('Uždaryti')",
            ".onetrust-close-btn-handler",
        ]

        for attempt in range(2):
            for selector in selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0:
                        btn.click(timeout=2000, force=True)
                        page.wait_for_timeout(300)
                        # Check if modal overlay is gone
                        try:
                            page.wait_for_selector(".onetrust-pc-dark-filter", state="hidden", timeout=2000)
                        except:
                            pass
                        return
                except Exception:
                    pass
            
            # If first pass failed, try using evaluate to click the button directly
            try:
                result = page.evaluate("""() => {
                    const btn = document.querySelector("button[id*='onetrust'][id*='accept']") ||
                               Array.from(document.querySelectorAll('button'))
                                 .find(b => b.innerText.includes('Leisti') || b.innerText.includes('Allow'));
                    if (btn) {
                        btn.click();
                        return true;
                    }
                    return false;
                }""")
                if result:
                    page.wait_for_timeout(500)
                    try:
                        page.wait_for_selector(".onetrust-pc-dark-filter", state="hidden", timeout=2000)
                    except:
                        pass
                    return
            except:
                pass
            
            page.wait_for_timeout(300)

    def extract_first_match(self, text: str, pattern: str) -> str:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    def normalize_text(self, page) -> str:
        raw_text = page.locator("body").inner_text(timeout=15000)
        return re.sub(r"\s+", " ", raw_text).strip()

    def wait_for_page_ready(self, page):
        """Wait for the page JS to finish rendering the custom-select widget."""
        # Step 1: accept cookies so the widget is not blocked by the modal overlay
        self.dismiss_cookie_modal(page)
        
        # Step 2: wait for the actual custom-select element to exist in DOM
        # This is the key step missing in CI — the widget renders AFTER cookies accepted
        print("    Waiting for fund selector to appear in DOM...")
        try:
            page.wait_for_selector(".custom-select-opener", timeout=30000)
            print("    ✓ Fund selector found in DOM")
        except Exception:
            raise RuntimeError("Fund selector never appeared in DOM after 30s")
        
        # Step 3: make sure cookie overlay is fully gone
        try:
            page.wait_for_selector("#onetrust-consent-sdk", state="hidden", timeout=5000)
        except Exception:
            # Force-remove the overlay via JS
            page.evaluate("document.getElementById('onetrust-consent-sdk')?.remove()")
            page.wait_for_timeout(300)

    def open_fund_selector(self, page):
        """Click the fund dropdown to open it."""
        for selector in self.FUND_SELECTOR_CANDIDATES:
            opener = page.locator(selector).first
            if opener.count() == 0:
                continue
            try:
                opener.scroll_into_view_if_needed(timeout=5000)
                opener.click(timeout=8000, force=True)
                page.wait_for_timeout(500)
                return
            except Exception as e:
                print(f"    ✗ Failed with {selector}: {str(e)[:80]}")
                continue

        # JavaScript fallback — removes any remaining overlay and clicks
        result = page.evaluate("""() => {
            document.getElementById('onetrust-consent-sdk')?.remove();
            const opener = document.querySelector('.custom-select-opener[role="combobox"]') ||
                           document.querySelector('.custom-select-opener') ||
                           document.querySelector('[role="combobox"]');
            if (opener) { opener.click(); return true; }
            return false;
        }""")
        if result:
            page.wait_for_timeout(500)
            return

        raise RuntimeError("Fund selector did not open.")

    def discover_fund_names(self, page) -> list:
        """Read fund names from visible options in the first selector."""
        self.open_fund_selector(page)

        fund_names = []
        options = page.locator(".custom-select-option:visible")
        for i in range(min(options.count(), 40)):
            text = options.nth(i).inner_text().strip()
            if text.startswith("Artea pensija") or text == "Artea pensijų turto išsaugojimo fondas":
                if text not in fund_names and text not in self.EXCLUDED_FUNDS:
                    fund_names.append(text)

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        return fund_names

    def select_fund(self, page, fund_name: str) -> bool:
        """Select a fund from currently opened selector."""
        try:
            locator = page.locator(f".custom-select-option:visible:has-text('{fund_name}')")
            if locator.count() > 0:
                locator.first.click(timeout=6000)
                page.wait_for_timeout(1000)
                return True
        except Exception as e:
            print(f"    CSS selector failed: {e}")

        # JavaScript fallback: find and click the option
        try:
            result = page.evaluate(f"""(fundName) => {{
                const options = document.querySelectorAll('.custom-select-option');
                for (let opt of options) {{
                    if (opt.innerText.includes(fundName)) {{
                        opt.click();
                        return true;
                    }}
                }}
                return false;
            }}""", fund_name)
            if result:
                page.wait_for_timeout(1000)
                return True
            else:
                print(f"    JS fallback: option not found for {fund_name}")
        except Exception as e:
            print(f"    JS fallback failed: {e}")

        return False

    def extract_metrics(self, page, fund_name: str) -> dict:
        text = self.normalize_text(page)
        return {
            "Fund name": fund_name,
            "Data": self.extract_first_match(text, r"Data\s+(\d{4}-\d{2}-\d{2})"),
            "Vieneto vertė": self.extract_first_match(text, r"Vieneto vertė\s+([0-9\s.,]+\s*EUR)"),
            "Grynieji aktyvai": self.extract_first_match(text, r"Grynieji aktyvai\s+([0-9\s.,]+\s*EUR)"),
        }

    def scrape_data(self, page) -> list:
        results = []

        page.wait_for_load_state("domcontentloaded")
        
        # Wait for cookies + custom-select widget to render — THIS is what CI needs
        self.wait_for_page_ready(page)

        fund_names = self.discover_fund_names(page)
        if not fund_names:
            print("  Warning: No fund names discovered")
            return results

        print(f"Detected {len(fund_names)} Artea funds")

        for idx, fund_name in enumerate(fund_names, start=1):
            print(f"[{idx}/{len(fund_names)}] Processing: {fund_name}")

            try:
                self.open_fund_selector(page)
                selected = self.select_fund(page, fund_name)
                if not selected:
                    print("    Could not select fund in dropdown.")
                    continue

                row = self.extract_metrics(page, fund_name)
                has_values = any(value for key, value in row.items() if key != "Fund name")
                if has_values:
                    results.append(row)
                else:
                    print("    No metrics extracted from page")
            except Exception as e:
                print(f"    Error processing fund: {e}")
                continue

        return results


if __name__ == "__main__":
    scraper = ArteaPensionsScraper()
    sys.exit(0 if scraper.run() else 1)
