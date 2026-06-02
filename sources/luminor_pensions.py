#!/usr/bin/env python3
"""
Luminor pension funds scraper.
Extracts II pillar fund data from a simple static table.
"""
import re
import sys
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

# Known Luminor II pillar fund IDs for the current live page.
LUMINOR_II_FUND_IDS = ["15", "16", "17", "18", "19", "20", "23", "21"]


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
        # New Luminor layout moved to /lt/rinkis-fonda; keep old URL as fallback
        return "https://www.luminor.lt/lt/rinkis-fonda"

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

        # First attempt: load known II-pillar fund pages directly by fund ID.
        try:
            self.dismiss_cookie_modal(page)
            found = 0
            for fund_id in LUMINOR_II_FUND_IDS:
                fund_url = f"{self.get_url()}?fund_type=pension&fund={fund_id}&currency=eur&period=3year"
                page.goto(fund_url, wait_until='networkidle', timeout=120000)
                self.dismiss_cookie_modal(page)

                fund_rates = page.evaluate('window.Drupal.settings.dnbPensionFunds.fundRates')
                fund_history = page.evaluate('window.Drupal.settings.dnbPensionFunds.fundRatesHistory')
                if not fund_rates or not fund_rates.get('name_alias_lt'):
                    continue

                data_date = None
                if isinstance(fund_history, dict):
                    date_keys = [
                        key
                        for key in fund_history.keys()
                        if re.match(r'^\d{4}-\d{2}-\d{2}$', key)
                    ]
                    if date_keys:
                        data_date = max(date_keys)

                unit_value = fund_rates.get('unit_price_eur') or fund_rates.get('unit_price')
                net_assets = fund_rates.get('nav_eur') or fund_rates.get('nav')
                if unit_value is None and net_assets is None:
                    continue

                results.append({
                    "Fund name": fund_rates.get('name_alias_lt'),
                    "Data": data_date,
                    "Vieneto vertė": unit_value,
                    "Grynieji aktyvai": net_assets,
                })
                found += 1

            if found:
                print(f"  Parsed {found} funds from Luminor live fund selector")
                return results
        except Exception as e:
            print("  Runtime selector parse failed:", e)

        # Fallback: legacy table scraping (old layout)
        rows = []
        table_selector = 'table[aria-describedby="funds-table-label"] tbody tr'
        for attempt in range(1, 4):
            page.wait_for_load_state("domcontentloaded")
            self.dismiss_cookie_modal(page)

            try:
                page.wait_for_selector(table_selector, timeout=30000)
            except Exception:
                pass

            rows = page.query_selector_all(table_selector)
            print(f"  Attempt {attempt}: found {len(rows)} table rows (legacy)")

            if len(rows) >= 6:
                break

            if attempt < 3:
                page.wait_for_timeout(2000)
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
