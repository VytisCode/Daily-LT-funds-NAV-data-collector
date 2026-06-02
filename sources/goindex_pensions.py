#!/usr/bin/env python3
"""
Goindex pension funds scraper.
Extracts II pillar fund data from a static table.
Table columns: fund name, 1d%, 1m%, 3m%, 1y%, 3y%, unit value, net assets, equity%
"""
import re
import sys
from datetime import datetime
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

    def wait_for_metrics_ready(self, page, timeout_ms: int = 20000) -> None:
        """Wait until numeric metric columns are populated in table rows."""
        deadline = page.evaluate("Date.now()") + timeout_ms
        while page.evaluate("Date.now()") < deadline:
            try:
                rows = page.query_selector_all("table tr")
                if len(rows) >= 2:
                    cells = rows[1].query_selector_all("td")
                    # Unit value (6) and net assets (7) should be non-empty when data is ready.
                    if len(cells) >= 8:
                        unit_value = cells[6].inner_text().strip()
                        net_assets = cells[7].inner_text().strip()
                        if unit_value and net_assets:
                            return
            except Exception:
                pass

            # Consent banner can reappear; attempt dismissal again while waiting.
            self.dismiss_cookie_modal(page)
            page.wait_for_timeout(500)

    def scrape_data(self, page) -> list:
        results = []

        target_table = None
        for attempt in range(1, 4):
            page.wait_for_load_state("domcontentloaded")
            self.dismiss_cookie_modal(page)

            # Goindex table can render after initial load on CI runners.
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                pass

            try:
                page.wait_for_selector("table", timeout=60000)
            except Exception:
                print("  Warning: table selector did not appear within 60s")

            tables = page.query_selector_all("table")
            print(f"  Attempt {attempt}: found {len(tables)} table(s)")

            for table in tables:
                txt = table.inner_text()
                if "Goindex pensija" in txt or "Goindex turto išsaugojimo" in txt:
                    target_table = table
                    break

            if target_table:
                # Wait until numeric columns are hydrated before parsing rows.
                self.wait_for_metrics_ready(page)
                break

            if attempt < 3:
                print("  Goindex table not ready yet, retrying...")
                page.wait_for_timeout(2500)
                page.reload(wait_until="domcontentloaded", timeout=60000)

        # Date is shown as "Data: 2026.04.16"
        data_date = None
        try:
            body = re.sub(r"\s+", " ", page.inner_text("body"))
            m = re.search(r"Data[:\s]+(\d{4})[.-](\d{2})[.-](\d{2})", body)
            if m:
                data_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            else:
                any_date = re.search(r"(\d{4})[.-](\d{2})[.-](\d{2})", body)
                if any_date:
                    data_date = f"{any_date.group(1)}-{any_date.group(2)}-{any_date.group(3)}"
        except Exception:
            pass

        if data_date is None:
            data_date = datetime.today().strftime("%Y-%m-%d")
            print("  Date value not found on page; using today's date as fallback.")

        print(f"  Data date: {data_date}")

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
    sys.exit(0 if scraper.run() else 1)
