#!/usr/bin/env python3
"""
Goindex pension funds scraper.
Extracts II pillar fund data from a static table.
Table columns: fund name, 1d%, 1m%, 3m%, 1y%, 3y%, unit value, net assets, equity%
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_scraper import BaseScraper
from send_email import send_notification_email


class GoindexPensionsScraper(BaseScraper):
    """Scrapes Goindex II pillar pension fund table."""

    URL = "https://www.goindex.lt/2-pakopa/fondu-rezultatai-ir-dokumentai/"
    API_SUMMARY_URL = "https://dapi.goindex.lt/v1/funds/summary/tab"
    DEFAULT_SECRET_KEY = "TiLnbKRfNniC4Udl8zCuYj2IjFoonGws8H231bdpgl4BAadjdr"
    FUND_CODE_MAP = {
        "GOX-03/09": "Goindex pensija 2003-2009",
        "GOX-54/60": "Goindex pensija 1954-1960",
        "GOX-61/67": "Goindex pensija 1961-1967",
        "GOX-68/74": "Goindex pensija 1968-1974",
        "GOX-75/81": "Goindex pensija 1975-1981",
        "GOX-82/88": "Goindex pensija 1982-1988",
        "GOX-89/95": "Goindex pensija 1989-1995",
        "GOX-96/02": "Goindex pensija 1996-2002",
        "GOX-TIPF": "Goindex pensijų turto išsaugojimo fondas",
    }

    def __init__(self):
        super().__init__("goindex_pensions")

    def get_url(self) -> str:
        return self.URL

    def get_api_secret_key(self) -> str:
        return os.getenv("GOINDEX_API_SECRET_KEY", self.DEFAULT_SECRET_KEY)

    def build_api_row(self, fund_code: str, record: dict) -> dict:
        date_value = record.get("date", "")
        if "T" in date_value:
            date_value = date_value.split("T")[0]
        return {
            "Fund name": self.FUND_CODE_MAP.get(fund_code, fund_code),
            "Data": date_value,
            "Vieneto vertė": record.get("unitValue"),
            "Grynieji aktyvai": record.get("assets"),
        }

    def fetch_summary_latest(self, fund_code: str) -> dict:
        query = urllib.parse.urlencode({
            "secret_key": self.get_api_secret_key(),
            "code": fund_code,
        })
        url = f"{self.API_SUMMARY_URL}?{query}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            if self.is_secret_key_error(exc.code, body):
                self.notify_secret_key_issue(exc.code, fund_code, body)
            raise

    def is_secret_key_error(self, status_code: int, body: str) -> bool:
        body_text = (body or "").lower()
        if status_code in {401, 403}:
            return True
        if status_code == 422 and "secret" in body_text:
            return True
        if "secret_key" in body_text or "invalid secret" in body_text or "expired" in body_text:
            return True
        return False

    def notify_secret_key_issue(self, status_code: int, fund_code: str, response_body: str) -> None:
        subject = "[Alert] Goindex API secret_key expired or invalid"
        body = (
            f"The Goindex API secret_key appears to be invalid or expired.\n"
            f"Fund code: {fund_code}\n"
            f"HTTP status: {status_code}\n"
            f"API URL: {self.API_SUMMARY_URL}\n"
            f"\n"
            "This script will fall back to the browser scraper for Goindex data.\n"
            "Please refresh the secret_key from the Goindex DevTools request and update the environment variable.\n"
            f"\nResponse body:\n{response_body[:2000]}"
        )
        send_notification_email(subject, body)

    def fetch_api_latest_data(self) -> list:
        results = []
        for fund_code in self.FUND_CODE_MAP:
            try:
                record = self.fetch_summary_latest(fund_code)
                if record:
                    results.append(self.build_api_row(fund_code, record))
                    print(f"Loaded latest Goindex data for {fund_code} via API")
                else:
                    raise RuntimeError("Empty API record")
            except urllib.error.HTTPError as exc:
                print(f"Goindex API fetch failed for {fund_code}: {exc}")
                return []
            except Exception as exc:
                print(f"Goindex API fetch failed for {fund_code}: {exc}")
                return []
        return results

    def run(self):
        try:
            api_results = self.fetch_api_latest_data()
            if api_results:
                print("Using Goindex API for latest fund data")
                df = pd.DataFrame(api_results)
                data_date = self._extract_data_date(df)
                filename = f"{self.source_name}_data_{data_date}.xlsx"
                filepath = self.save_to_excel(df, filename)
                if filepath:
                    print(f"✅ Excel file created: {filename}")
                return filepath
        except Exception as exc:
            print(f"Goindex API path failed: {exc}. Falling back to browser scraping.")

        return super().run()

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
