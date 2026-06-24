#!/usr/bin/env python3
"""
Vestel Portal - Günlük Öğle Yemeği Menüsü Scraper (Playwright)
GitHub Actions her gün 06:00 UTC (09:00 TR) tetikler.
"""

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PORTAL_URL = "https://portal.vestel.com.tr/irj/portal"

PORTAL_USER = os.environ["PORTAL_USER"]
PORTAL_PASS = os.environ["PORTAL_PASS"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENTS = [r.strip() for r in os.environ["MAIL_RECIPIENTS"].split(",")]


def get_menu() -> list[str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("→ Portal açılıyor…")
        page.goto(PORTAL_URL, wait_until="networkidle", timeout=60_000)

        # Login formu görünüyorsa doldur
        if page.locator('input[name="j_user"]').count() > 0:
            print("  Login formu bulundu, giriş yapılıyor…")
            page.fill('input[name="j_user"]', PORTAL_USER)
            page.fill('input[name="j_password"]', PORTAL_PASS)
            page.click('input[type="submit"], button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=60_000)
            print(f"  Login sonrası URL: {page.url}")

        # Öğle Yemeği Menüsü bölümünü bekle
        print("→ Menü aranıyor…")
        try:
            page.wait_for_selector(
                'text=/[ÖO]ğle Yeme/i',
                timeout=20_000,
            )
        except PWTimeout:
            # Sayfa içeriğini dump et (ilk 2000 karakter)
            snippet = page.inner_text("body")[:2000].replace("\n", " | ")
            print(f"  Menü başlığı bulunamadı. Sayfa içeriği: {snippet}", file=sys.stderr)
            browser.close()
            return []

        # Menü kalemlerini topla — başlığın parent container'ındaki text node'lar
        items: list[str] = []

        # İlk yöntem: "Öğle Yemeği Menüsü" yazısını içeren bloğun kardeş/çocuk elementleri
        menu_section = page.locator('text=/[ÖO]ğle Yeme/i').first
        # Üst container'a çık (3 seviye)
        container = menu_section.locator("xpath=ancestor::*[3]")
        raw = container.inner_text()
        for line in raw.splitlines():
            line = line.strip()
            if line and len(line) > 2 and "ğle Yeme" not in line and "12:00" not in line:
                items.append(line)

        browser.close()
        print(f"  {len(items)} kalem bulundu")
        return items


def build_email(items: list[str], date_str: str):
    subject = f"Bugünkü Öğle Yemeği Menüsü — {date_str}"
    html_items = "".join(f"<li>{item}</li>" for item in items)
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#c0392b;border-bottom:2px solid #c0392b;padding-bottom:8px">
        Öğle Yemeği Menüsü
      </h2>
      <p style="color:#555">{date_str} &middot; 12:00 / 20:00 / 00:00</p>
      <ul style="font-size:15px;line-height:2">{html_items}</ul>
      <p style="color:#aaa;font-size:12px;margin-top:24px">Bu e-posta otomatik olarak gönderilmiştir.</p>
    </body></html>
    """
    plain = f"Öğle Yemeği Menüsü — {date_str}\n\n" + "\n".join(f"• {i}" for i in items)
    return subject, html, plain


def send_email(subject: str, html: str, plain: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENTS, msg.as_string())

    print(f"✓ Mail gönderildi → {', '.join(RECIPIENTS)}")


def main() -> None:
    from datetime import date
    today = date.today().strftime("%d %B %Y")

    items = get_menu()
    if not items:
        print("⚠ Menü bulunamadı, mail gönderilmedi.", file=sys.stderr)
        sys.exit(1)
    print(f"✓ {len(items)} kalem: {items}")

    subject, html, plain = build_email(items, today)
    send_email(subject, html, plain)


if __name__ == "__main__":
    main()
