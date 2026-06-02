#!/usr/bin/env python3
"""
Send the merged pension data Excel file via Gmail.
"""
import smtplib
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path
import sys
import os
import re


def load_dotenv(dotenv_path=".env"):
    env_file = Path(dotenv_path)
    if not env_file.exists():
        return

    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

# Configuration
GMAIL_USER = os.getenv("GMAIL_USER")  # e.g., your.email@gmail.com
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")  # App-specific password
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")


def get_latest_excel_file():
    files = sorted(Path(".").glob("pension_data_combined_*.xlsx"))
    if not files:
        return None, None
    latest_file = max(files, key=lambda path: path.stat().st_mtime)
    # Extract date from filename: pension_data_combined_YYYY-MM-DD.xlsx
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', latest_file.name)
    data_date = date_match.group(1).replace('-', '.') if date_match else "unknown"
    return latest_file, data_date

def send_email():
    """Send the Excel file via Gmail."""
    excel_file, data_date = get_latest_excel_file()
    recipients = [addr.strip() for addr in (RECIPIENT_EMAIL or "").split(",") if addr.strip()]
    
    # Validate inputs
    if not GMAIL_USER:
        print("Error: GMAIL_USER environment variable not set")
        print("Set it in .env or run with GMAIL_USER=your.email@gmail.com GMAIL_PASSWORD='your app password' python3 send_email.py")
        sys.exit(1)
    
    if not GMAIL_PASSWORD:
        print("Error: GMAIL_PASSWORD environment variable not set")
        print("Set it in .env or run with GMAIL_USER=your.email@gmail.com GMAIL_PASSWORD='your app password' python3 send_email.py")
        sys.exit(1)
    
    if not excel_file:
        print("Error: no merged Excel file found. Run merge_data.py first.")
        sys.exit(1)

    if not recipients:
        print("Error: RECIPIENT_EMAIL environment variable not set")
        print("Set it in .env, for example: RECIPIENT_EMAIL=person@example.com")
        sys.exit(1)
    
    print(f"Sending {excel_file.name}...")
    print(f"  From: {GMAIL_USER}")
    print(f"  To: {', '.join(recipients)}")
    print(f"  Data date: {data_date}")
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg["From"] = GMAIL_USER
        msg["To"] = ", ".join(recipients)
        msg["Date"] = formatdate(localtime=True)
        msg["Subject"] = f"LT Pension Fund Data - {data_date}"
        
        # Body
        body = f"""
Hello,
Please find the attached latest data on Lithuanian pension funds for {data_date}, including performance metrics and fund sizes.
Best regards,
Automated Python Script
"""
        msg.attach(MIMEText(body, "plain"))
        
        # Attach Excel file
        with open(excel_file, "rb") as attachment:
            part = MIMEBase(
                "application",
                "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        
        part.add_header("Content-Disposition", f"attachment; filename={excel_file.name}")
        msg.attach(part)
        
        # Send email
        print("\nConnecting to Gmail SMTP server...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.send_message(msg, to_addrs=recipients)
        
        print(f"✅ Email sent successfully to {', '.join(recipients)}")
        
    except smtplib.SMTPAuthenticationError:
        print("❌ Error: Gmail login failed. Check your credentials.")
        print("   Make sure you're using an app-specific password, not your regular password.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        sys.exit(1)

if __name__ == "__main__":
    send_email()
