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
            args=["--disable-blink-features=AutomationControlled"],
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
        selectors = [
            "#onetrust-reject-all-handler",
            "#onetrust-accept-btn-handler",
            "button:has-text('Leisti visus')",
            "button:has-text('Patvirtinti pasirinkimus')",
            "button:has-text('Uždaryti')",
            ".onetrust-close-btn-handler",
        ]

        for _ in range(6):
            for selector in selectors:
                try:
                    page.locator(selector).first.click(timeout=1500, force=True)
                except Exception:
                    pass
            page.wait_for_timeout(250)

    def extract_first_match(self, text: str, pattern: str) -> str:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    def normalize_text(self, page) -> str:
        raw_text = page.locator("body").inner_text(timeout=15000)
        return re.sub(r"\s+", " ", raw_text).strip()

    def open_fund_selector(self, page):
        """Open the first combobox, which is the fund chooser."""
        opener = page.locator(".custom-select-opener[role='combobox']").first
        opener.click(timeout=30000)
        page.wait_for_timeout(450)

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

        # Close selector after discovery.
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        return fund_names

    def select_fund(self, page, fund_name: str) -> bool:
        """Select a fund from currently opened selector."""
        locator = page.locator(f".custom-select-option:visible:has-text('{fund_name}')")
        if locator.count() == 0:
            return False

        locator.first.click(timeout=10000)
        page.wait_for_timeout(2300)
        return True

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
        page.wait_for_timeout(2000)
        self.dismiss_cookie_modal(page)

        fund_names = self.discover_fund_names(page)
        print(f"Detected {len(fund_names)} Artea funds")

        for idx, fund_name in enumerate(fund_names, start=1):
            print(f"[{idx}/{len(fund_names)}] Processing: {fund_name}")

            self.open_fund_selector(page)
            selected = self.select_fund(page, fund_name)
            if not selected:
                print("  Could not select fund in dropdown.")
                continue

            row = self.extract_metrics(page, fund_name)
            has_values = any(value for key, value in row.items() if key != "Fund name")
            if has_values:
                results.append(row)

        return results


if __name__ == "__main__":
    scraper = ArteaPensionsScraper()
    scraper.run()
