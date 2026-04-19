#!/usr/bin/env python3
"""
Goindex pension funds scraper.
Extracts II pillar fund data from a static table.
Table columns: fund name, 1d%, 1m%, 3m%, 1y%, 3y%, unit value, net assets, equity%
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_scraper import BaseScraper


class GoindexPensionsScraper(BaseScraper):
    """Scrapes Goindex II pillar pension fund table."""

    URL = "https://www.goindex.lt/2-pakopa/fondu-rezultatai-ir-dokumentai/"

    def __init__(self):
        super().__init__("goindex_pensions")

    def get_url(self) -> str:
        return self.URL

    def dismiss_cookie_modal(self, page):
        for sel in [
            "button:has-text('Leisti visus')",
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
        page.wait_for_selector("table", timeout=30000)
        self.dismiss_cookie_modal(page)

        # Date is shown as "Data: 2026.04.16"
        data_date = None
        try:
            body = page.inner_text("body")
            m = re.search(r"Data[:\s]+(\d{4})\.(\d{2})\.(\d{2})", body)
            if m:
                data_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except Exception:
            pass

        print(f"  Data date: {data_date}")

        # Find the table containing Goindex fund rows
        tables = page.query_selector_all("table")
        print(f"  Found {len(tables)} tables")

        target_table = None
        for table in tables:
            txt = table.inner_text()
            if "Goindex pensija" in txt:
                target_table = table
                break

        if not target_table:
            print("  Could not find Goindex pension fund table.")
            return results

        rows = target_table.query_selector_all("tr")
        print(f"  Rows in target table: {len(rows)}")

        for row in rows:
            cells = row.query_selector_all("td")
            # Columns: name(0), 1d%(1), 1m%(2), 3m%(3), 1y%(4), 3y%(5), unit_value(6), net_assets(7)
            if len(cells) < 8:
                continue

            fund_name = " ".join(cells[0].inner_text().split())
            if not fund_name or not fund_name.startswith("Goindex"):
                continue

            unit_value = cells[6].inner_text().strip()
            net_assets = cells[7].inner_text().strip()

            results.append({
                "Fund name": fund_name,
                "Data": data_date,
                "Vieneto vertė": unit_value,
                "Grynieji aktyvai": net_assets,
            })

        return results


if __name__ == "__main__":
    scraper = GoindexPensionsScraper()
    scraper.run()
