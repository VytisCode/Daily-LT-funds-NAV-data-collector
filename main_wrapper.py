#!/usr/bin/env python3
"""
Retry wrapper for run_daily_pipeline.py.

Features:
- Runs pipeline up to 3 attempts.
- Logs steps and errors to console and logs/main_wrapper.log.
- Sends an email notification if all attempts fail.
- Uses environment variables for credentials:
  GMAIL_USER, GMAIL_PASSWORD, RECIPIENT_EMAIL
"""

from __future__ import annotations

import logging
import os
import smtplib
import subprocess
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "main_wrapper.log"
PIPELINE_SCRIPT = BASE_DIR / "run_daily_pipeline.py"
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 30


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)

    logger = logging.getLogger("main_wrapper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger


def read_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and (value is None or not value.strip()):
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip() if isinstance(value, str) else value


def send_failure_email(logger: logging.Logger, subject: str, body: str) -> None:
    try:
        email_user = read_env("GMAIL_USER", required=True)
        email_pass = read_env("GMAIL_PASSWORD", required=True)
        to_email = read_env("RECIPIENT_EMAIL", required=True)

        recipients = [addr.strip() for addr in to_email.split(",") if addr.strip()]
        if not recipients:
            raise ValueError("RECIPIENT_EMAIL has no valid recipients")

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = ", ".join(recipients)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_pass)
            server.sendmail(email_user, recipients, msg.as_string())

        logger.info("Failure email sent to %s", ", ".join(recipients))
    except Exception as exc:
        logger.exception("Unable to send failure email: %s", exc)


def run_pipeline(logger: logging.Logger) -> tuple[bool, str]:
    """Run run_daily_pipeline.py and return (success, combined_output)."""
    command = [sys.executable, str(PIPELINE_SCRIPT)]
    logger.info("Executing command: %s", " ".join(command))

    proc = subprocess.run(
        command,
        cwd=BASE_DIR,
        text=True,
        check=False,
    )

    if proc.returncode == 0:
        logger.info("Pipeline succeeded")
        return True, ""

    logger.error("Pipeline failed with exit code %s", proc.returncode)
    return False, ""


def main() -> int:
    logger = setup_logging()
    logger.info("Starting main_wrapper at %s", datetime.now(timezone.utc).isoformat())

    if not PIPELINE_SCRIPT.exists():
        logger.error("Missing script: %s", PIPELINE_SCRIPT)
        return 1

    last_output = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("Attempt %d/%d", attempt, MAX_ATTEMPTS)
        try:
            success, combined_output = run_pipeline(logger)
            last_output = combined_output
            if success:
                logger.info("Pipeline succeeded on attempt %d", attempt)
                return 0
        except Exception as exc:
            logger.exception("Unexpected exception on attempt %d: %s", attempt, exc)

        if attempt < MAX_ATTEMPTS:
            logger.info("Retrying in %d seconds...", RETRY_DELAY_SECONDS)
            time.sleep(RETRY_DELAY_SECONDS)

    logger.error("All %d attempts failed", MAX_ATTEMPTS)

    subject = "[ALERT] Pension pipeline failed after retries"
    body = (
        "Pipeline run failed after 3 attempts.\n\n"
        f"Time (UTC): {datetime.now(timezone.utc).isoformat()}\n"
        f"Repository path: {BASE_DIR}\n"
        f"Log file: {LOG_FILE}\n\n"
        "Last captured output:\n"
        f"{last_output[-10000:]}"
    )
    send_failure_email(logger, subject, body)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
