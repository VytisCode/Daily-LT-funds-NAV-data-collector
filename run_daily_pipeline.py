#!/usr/bin/env python3
"""
Daily pipeline orchestrator - auto-discovers and runs all scrapers.
"""
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import os

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PYTHON = BASE_DIR / ".venv" / "bin" / "python3"
LOG_DIR = BASE_DIR / "logs"
SOURCES_DIR = BASE_DIR / "sources"
STEP_TIMEOUT_SECONDS = int(os.getenv("PIPELINE_STEP_TIMEOUT_SECONDS", "420"))
SCRAPER_RETRIES = int(os.getenv("PIPELINE_SCRAPER_RETRIES", "1"))
STRICT_FAILURE_MODE = os.getenv("PIPELINE_STRICT_FAILURE", "0") == "1"


def get_python_executable():
    if DEFAULT_PYTHON.exists():
        return DEFAULT_PYTHON
    return Path(sys.executable)


def discover_scrapers():
    """
    Auto-discover all scraper scripts in the sources/ directory.
    Excludes files starting with underscore or 'template'.
    
    Returns:
        List of scraper script paths in sources/ folder
    """
    scrapers = []
    
    if not SOURCES_DIR.exists():
        print(f"Warning: sources/ directory not found at {SOURCES_DIR}")
        return scrapers
    
    for script_file in sorted(SOURCES_DIR.glob("*.py")):
        # Skip private files, templates, and __init__.py
        if script_file.name.startswith("_") or "template" in script_file.name:
            continue
        
        scrapers.append(script_file)
    
    return scrapers


def run_step(script_path, timeout_seconds=STEP_TIMEOUT_SECONDS, retries=0):
    """
    Run a single script/scraper with a timeout.
    
    Args:
        script_path: Full path to the script to run

    Returns:
        True if the step completed successfully, False otherwise.
    """
    command = [str(get_python_executable()), str(script_path)]
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        print(f"\n=== Running {script_path.name} (attempt {attempt}/{attempts}) ===")
        try:
            result = subprocess.run(command, cwd=BASE_DIR, check=False, timeout=timeout_seconds)
            if result.returncode == 0:
                return True
            print(f"{script_path.name} failed with exit code {result.returncode}")
        except subprocess.TimeoutExpired:
            print(f"{script_path.name} timed out after {timeout_seconds} seconds")

        if attempt < attempts:
            print(f"Retrying {script_path.name}...")

    return False


def main():
    python_executable = get_python_executable()
    if not python_executable.exists():
        print(f"Missing Python interpreter: {python_executable}")
        sys.exit(1)

    LOG_DIR.mkdir(exist_ok=True)
    print(f"Starting daily workflow at {datetime.now().isoformat(timespec='seconds')}")

    # Step 1: Discover and run all scrapers
    scrapers = discover_scrapers()
    failed_scrapers = []
    
    if not scrapers:
        print("Warning: No scrapers found in sources/ directory")
    else:
        print(f"Found {len(scrapers)} scraper(s): {', '.join(s.name for s in scrapers)}")
        for scraper_path in scrapers:
            success = run_step(scraper_path, retries=SCRAPER_RETRIES)
            if not success:
                failed_scrapers.append(scraper_path.name)

    # Step 2: Merge data from all sources
    print("\n=== Running merge_data.py ===")
    merge_script = BASE_DIR / "merge_data.py"
    if merge_script.exists():
        merge_success = run_step(merge_script, retries=0)
        if not merge_success:
            print("Merge step failed. Skipping email sending.")
            if failed_scrapers:
                print(f"Failed scrapers: {', '.join(failed_scrapers)}")
            sys.exit(1)
    else:
        print(f"Warning: {merge_script} not found")

    # Step 3: Send email
    print("\n=== Running send_email.py ===")
    email_script = BASE_DIR / "send_email.py"
    if email_script.exists():
        email_success = run_step(email_script, retries=0)
        if not email_success:
            print("Email step failed.")
            if failed_scrapers:
                print(f"Failed scrapers: {', '.join(failed_scrapers)}")
            sys.exit(1)
    else:
        print(f"Warning: {email_script} not found")

    if failed_scrapers:
        print(f"Workflow completed with failures in: {', '.join(failed_scrapers)}")
        if STRICT_FAILURE_MODE:
            print("Strict mode enabled: exiting with error because at least one scraper failed.")
            sys.exit(1)
        print("Strict mode disabled: report sent using latest available data from each source.")
        sys.exit(0)

    print(f"Workflow completed at {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Workflow failed: {exc}")
        sys.exit(1)
