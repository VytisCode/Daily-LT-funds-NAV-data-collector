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


class LuminorPensionsScraper(BaseScraper):
    """Scrapes Luminor II pillar pension fund table."""

    def __init__(self):
        super().__init__("luminor_pensions")

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

        page.wait_for_load_state("domcontentloaded")
        self.dismiss_cookie_modal(page)

        # Luminor table can render asynchronously; wait for table cells instead of fixed sleeps.
        try:
            page.wait_for_selector("table td", timeout=30000)
        except Exception:
            # Retry once after an extra short wait in case cookie/UI overlays delayed rendering.
            page.wait_for_timeout(2000)
            page.wait_for_selector("table td", timeout=30000)

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

        rows = page.query_selector_all("table tr")
        print(f"  Found {len(rows)} table rows")

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
    scraper.run()
