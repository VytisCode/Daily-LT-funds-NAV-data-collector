#!/usr/bin/env python3
"""
Luminor pension funds scraper.
Extracts II pillar fund data from a simple static table.
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_scraper import BaseScraper

# Exclude III pillar funds
EXCLUDED_FUNDS = {
    "Luminor ateitis 16–50",
    "Luminor ateitis 50–58",
    "Luminor ateitis 58+",
    "Luminor tvari ateitis index",
    "Luminor ateitis akcijų index",
}


class LuminorPensionsScraper(BaseScraper):
    """Scrapes Luminor II pillar pension fund table."""

    def __init__(self):
        super().__init__("luminor_pensions")

    def setup_browser(self):
        """Use a more realistic browser fingerprint for Luminor to avoid bot blocking."""
        from playwright.sync_api import sync_playwright

        print("Starting browser (Luminor-specific settings)...")
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=self._is_headless(),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
            ],
        )
        context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="lt-LT",
            timezone_id="Europe/Vilnius",
        )
        self.page = context.new_page()
        try:
            self.page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        except Exception:
            pass
        return self.page

    def get_url(self) -> str:
        return "https://www.luminor.lt/lt/pensiju-fondai"

    def dismiss_cookie_modal(self, page):
        for sel in [
            "button:has-text('PRIIMTI VISUS')",
            "button:has-text('Priimti visus')",
            "#onetrust-accept-btn-handler",
        ]:
            try:
                page.locator(sel).first.click(timeout=3000, force=True)
                break
            except Exception:
                pass
        page.wait_for_timeout(500)

    def scrape_data(self, page) -> list:
        results = []

        rows = []
        # Target the specific table with aria-describedby for more robust selection.
        table_selector = 'table[aria-describedby="funds-table-label"] tbody tr'
        for attempt in range(1, 5):
            page.wait_for_load_state("domcontentloaded")
            self.dismiss_cookie_modal(page)

            try:
                page.wait_for_selector(table_selector, timeout=45000)
            except Exception:
                pass

            rows = page.query_selector_all(table_selector)
            print(f"  Attempt {attempt}: found {len(rows)} table rows")

            if len(rows) >= 6:
                break

            if attempt < 4:
                print("  Luminor table not ready yet, retrying...")
                page.wait_for_timeout(3000)
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass

        # Extract date shown above the table
        data_date = None
        try:
            body = page.inner_text("body")
            m = re.search(r"Vieneto verčių data[:\s]+(\d{4})[.-](\d{2})[.-](\d{2})", body)
            if m:
                data_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except Exception:
            pass

        print(f"  Data date: {data_date}")

        print(f"  Found {len(rows)} table rows")

        # If we couldn't find a reasonable number of rows, dump page HTML and screenshot
        # to help debugging in CI (upload artifacts from workflow).
        if len(rows) < 6:
            try:
                dump_dir = Path("artifacts")
                dump_dir.mkdir(exist_ok=True)
                dump_html = dump_dir / f"luminor_page_dump_{int(time.time())}.html"
                content = page.content()
                dump_html.write_text(content, encoding="utf-8")
                print(f"  Wrote page HTML dump to {dump_html}")
            except Exception as e:
                print("  Failed to write HTML dump:", e)

            try:
                screenshot_path = dump_dir / f"luminor_page_screenshot_{int(time.time())}.png"
                page.screenshot(path=str(screenshot_path), full_page=True)
                print(f"  Wrote screenshot to {screenshot_path}")
            except Exception as e:
                print("  Failed to write screenshot:", e)

        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 4:
                continue

            fund_name = cells[0].inner_text().strip()
            if not fund_name or fund_name in EXCLUDED_FUNDS:
                continue

            unit_value = cells[1].inner_text().strip().replace("EUR", "").strip()
            net_assets = cells[3].inner_text().strip()

            results.append({
                "Fund name": fund_name,
                "Data": data_date,
                "Vieneto vertė": unit_value,
                "Grynieji aktyvai": net_assets,
            })

        return results


if __name__ == "__main__":
    scraper = LuminorPensionsScraper()
    sys.exit(0 if scraper.run() else 1)
