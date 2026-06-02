#!/usr/bin/env python3
"""
Artea pension funds scraper.
Handles a clickable expandable fund selector and extracts key fund metrics.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
try:
    import playwright_stealth as pw_stealth
except ImportError:
    pw_stealth = None

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
            extra_http_headers={
                "Accept-Language": "lt-LT,lt;q=0.9,en;q=0.8",
                "Referer": "https://www.google.com/",
            },
        )
        self.page = context.new_page()
        self.page.set_default_timeout(45000)
        
        # Apply stealth measures if available
        if pw_stealth and hasattr(pw_stealth, "Stealth"):
            print("  Applying Playwright stealth measures...")
            pw_stealth.Stealth().apply_stealth_sync(self.page)
        else:
            print("  Warning: playwright-stealth not installed or import failed. Install with: pip install playwright-stealth")
        
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            "Object.defineProperty(navigator, 'languages', {get: () => ['lt-LT','lt','en-US','en']});"
            "Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});"
            "window.navigator.chrome = { runtime: {} };"
        )
        return self.page

    def cleanup_browser(self):
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()

    def dismiss_cookie_modal(self, page):
        """Dismiss OneTrust modal/panel that can block clicks."""
        # Use JavaScript to aggressively dismiss and hide all consent modals
        page.evaluate("""() => {
            // Try to click accept button - use valid CSS selectors only
            const buttons = [
                document.getElementById('onetrust-accept-btn-handler'),
                document.querySelector('.onetrust-close-btn-handler'),
                document.querySelector('[data-testid="cookie-accept-button"]'),
                document.querySelector("button[id*='accept']"),
                // Find button by text content (without :has-text which is Playwright-only)
                Array.from(document.querySelectorAll('button')).find(b => 
                    (b.innerText || '').includes('Leisti') || (b.innerText || '').includes('Accept') || (b.innerText || '').includes('Patvirt')
                ),
            ].filter(Boolean);
            
            for (let btn of buttons) {
                try {
                    btn.click();
                } catch(e) {}
            }
            
            // Force hide overlay
            const overlay = document.querySelector('.onetrust-pc-dark-filter') ||
                           document.getElementById('onetrust-consent-sdk');
            if (overlay) {
                overlay.style.display = 'none';
                overlay.style.visibility = 'hidden';
                overlay.style.zIndex = '-9999';
                overlay.style.pointerEvents = 'none';
            }
            
            // Remove modal from DOM if still present
            try {
                document.getElementById('onetrust-consent-sdk')?.remove();
            } catch(e) {}
        }""")
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
        print("    Waiting for page to stabilize...")
        
        # Check for Cloudflare challenge page
        print("    Checking for Cloudflare security challenge...")
        page.wait_for_timeout(5000)  # Give Cloudflare time to load dynamic content
        
        cf_challenge = page.evaluate("""() => {
            const text = document.body.innerText || '';
            return text.includes('Saugumo patvirtinimo') || 
                   text.includes('security challenge') ||
                   text.includes('Ray ID');
        }""")
        
        if cf_challenge:
            print("    ⚠️  Cloudflare security challenge detected!")
            print("    Waiting up to 60s for Cloudflare to verify...")
            try:
                # Wait for the challenge to complete by checking if the page content changes
                page.wait_for_function("""() => {
                    const text = document.body.innerText || '';
                    return !text.includes('Saugumo patvirtinimo') && 
                           !text.includes('Ray ID') &&
                           document.querySelectorAll('.custom-select-opener').length > 0;
                }""", timeout=60000)
                print("    ✓ Cloudflare challenge completed")
            except Exception as e:
                print(f"    ✗ Cloudflare challenge not bypassed: {e}")
                raise RuntimeError("Cloudflare security challenge could not be bypassed in headless mode")
        
        # Step 1: Aggressively dismiss cookie modal
        print("    Dismissing cookie consent modal...")
        for attempt in range(3):
            self.dismiss_cookie_modal(page)
            page.wait_for_timeout(500)
            
            # Check if overlay is gone
            overlay_gone = page.evaluate("""() => {
                const overlay = document.querySelector('.onetrust-pc-dark-filter') ||
                               document.getElementById('onetrust-consent-sdk');
                return !overlay || window.getComputedStyle(overlay).display === 'none';
            }""")
            if overlay_gone:
                print("    ✓ Cookie modal dismissed")
                break
        
        # Step 2: Wait for the custom-select element to exist in DOM
        print("    Waiting for fund selector to appear in DOM...")
        selector_found = False
        for attempt in range(3):
            try:
                page.wait_for_selector(".custom-select-opener", timeout=10000)
                selector_found = True
                print("    ✓ Fund selector found in DOM")
                break
            except Exception:
                if attempt < 2:
                    print(f"    Selector not found (attempt {attempt + 1}/3), retrying...")
                    page.wait_for_timeout(1000)
                else:
                    print("    ✗ Fund selector not found after 3 attempts")
        
        if not selector_found:
            # Debug: check what's actually on the page
            debug_info = page.evaluate("""() => {
                return {
                    hasOverlay: !!document.querySelector('.onetrust-pc-dark-filter'),
                    hasSelector: !!document.querySelector('.custom-select-opener'),
                    bodyText: document.body.innerText.substring(0, 300)
                };
            }""")
            raise RuntimeError(
                f"Fund selector never appeared. Debug: {debug_info}"
            )

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
