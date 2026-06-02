#!/usr/bin/env python3
"""
Allianz pension funds scraper.
Extracts II pillar (gyvenimo ciklo) fund data from a static table.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_scraper import BaseScraper

# Exclude the liquidated Allianz B fund (zero assets)
EXCLUDED_FUNDS = {
    "Allianz B gimusiems 1954-1960 m.",
}


class AllianzPensionsScraper(BaseScraper):
    """Scrapes Allianz gyvenimo ciklo pension fund table."""

    URL = "https://investavimorezultatai.allianz.lt/?tipas=gyvenimo-ciklo-pensiju-fondai"

    def __init__(self):
        super().__init__("allianz_pensions")

    def get_url(self) -> str:
        return self.URL

    def dismiss_cookie_modal(self, page):
        for sel in [
            "button:has-text('Sutinku')",
            "button:has-text('Priimti')",
            "button:has-text('Accept')",
            "#onetrust-accept-btn-handler",
        ]:
            try:
                page.locator(sel).first.click(timeout=2000, force=True)
                break
            except Exception:
                pass
        page.wait_for_timeout(500)

    def scrape_data(self, page) -> list:
        results = []

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        self.dismiss_cookie_modal(page)

        # Extract date — page shows Lithuanian format "2026 m. balandžio 16 d."
        # Convert to ISO format using a month name mapping.
        data_date = None
        LT_MONTHS = {
            "sausio": "01", "vasario": "02", "kovo": "03", "balandžio": "04",
            "gegužės": "05", "birželio": "06", "liepos": "07", "rugpjūčio": "08",
            "rugsėjo": "09", "spalio": "10", "lapkričio": "11", "gruodžio": "12",
        }
        try:
            body = page.inner_text("body")
            m = re.search(r"(\d{4})\s+m\.\s+(\S+)\s+(\d{1,2})\s+d\.", body)
            if m:
                year, month_lt, day = m.group(1), m.group(2).lower(), m.group(3)
                month_num = LT_MONTHS.get(month_lt)
                if month_num:
                    data_date = f"{year}-{month_num}-{int(day):02d}"
        except Exception:
            pass

        print(f"  Data date: {data_date}")

        # Find the table containing Allianz pension fund rows
        tables = page.query_selector_all("table")
        print(f"  Found {len(tables)} tables")

        target_table = None
        for table in tables:
            txt = table.inner_text()
            if "Allianz" in txt and ("1961" in txt or "1968" in txt or "išsaugojimo" in txt):
                target_table = table
                break

        if not target_table:
            print("  Could not find Allianz pension fund table.")
            return results

        rows = target_table.query_selector_all("tr")
        print(f"  Rows in target table: {len(rows)}")

        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 3:
                continue

            # Fund name spans two lines — join and normalise whitespace
            fund_name = " ".join(cells[0].inner_text().split())
            if not fund_name or fund_name in EXCLUDED_FUNDS:
                continue

            # Unit value is cell[1], net assets is cell[4]
            unit_value_raw = cells[1].inner_text().strip()
            unit_value = re.split(r"[\s\xa0]+[+\-]", unit_value_raw)[0].strip()

            net_assets = " ".join(cells[4].inner_text().split()) if len(cells) > 4 else ""

            results.append({
                "Fund name": fund_name,
                "Data": data_date,
                "Vieneto vertė": unit_value,
                "Grynieji aktyvai": net_assets,
            })

        return results


if __name__ == "__main__":
    scraper = AllianzPensionsScraper()
    sys.exit(0 if scraper.run() else 1)
