#!/usr/bin/env python3
"""
Vestel Portal - Günlük Öğle Yemeği Menüsü Scraper
Çalışma: GitHub Actions her gün 06:00 UTC (09:00 TR) tetikler
"""

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

PORTAL_URL = "https://portal.vestel.com.tr/irj/portal"
LOGIN_URL = "https://portal.vestel.com.tr/irj/servlet/prt/portal/prtroot/com.sap.portal.navigation.loginform"

PORTAL_USER = os.environ["PORTAL_USER"]
PORTAL_PASS = os.environ["PORTAL_PASS"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
# Virgülle ayrılmış alıcılar: "a@x.com,b@x.com"
RECIPIENTS = [r.strip() for r in os.environ["MAIL_RECIPIENTS"].split(",")]


SAP_LOGIN_ENDPOINT = (
    "https://portal.vestel.com.tr/irj/servlet/prt/portal/prtroot/"
    "com.sap.portal.navigation.loginform"
)
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def login() -> requests.Session:
    session = requests.Session()
    session.headers.update(BASE_HEADERS)

    # SAP Netweaver: önce login sayfasını GET et (oturum çerezi + hidden token)
    # 401 gelirse Basic Auth ile dene
    login_page = session.get(
        SAP_LOGIN_ENDPOINT,
        auth=(PORTAL_USER, PORTAL_PASS),
        allow_redirects=True,
        timeout=30,
    )

    soup = BeautifulSoup(login_page.text, "html.parser")

    # Hidden input'ları topla (CSRF / SAP token)
    payload: dict = {}
    form = soup.find("form")
    if form:
        for inp in form.find_all("input", {"type": "hidden"}):
            if inp.get("name"):
                payload[inp["name"]] = inp.get("value", "")

    payload.update({
        "j_user": PORTAL_USER,
        "j_password": PORTAL_PASS,
        "action": "login",
    })

    # Form action URL'ini belirle
    if form and form.get("action"):
        action = form["action"]
        if action.startswith("/"):
            action = "https://portal.vestel.com.tr" + action
    else:
        action = SAP_LOGIN_ENDPOINT

    login_resp = session.post(
        action,
        data=payload,
        auth=(PORTAL_USER, PORTAL_PASS),
        allow_redirects=True,
        timeout=30,
    )

    # Debug: HTTP durum kodu ve URL yazdır
    print(f"  Login POST → {login_resp.status_code} | final URL: {login_resp.url}")

    if login_resp.status_code == 401:
        raise RuntimeError("401 Unauthorized — kullanıcı adı/şifre hatalı veya IP kısıtlaması var")

    login_resp.raise_for_status()

    if "j_user" in login_resp.text and "j_password" in login_resp.text:
        raise RuntimeError("Giriş başarısız — hâlâ login sayfasında")

    return session


def fetch_menu(session: requests.Session) -> list[str]:
    """Öğle Yemeği Menüsü kalemlerini döner."""
    resp = session.get(PORTAL_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # "Öğle Yemeği Menüsü" başlığını bul
    oglen_header = None
    for el in soup.find_all(string=lambda t: t and "ğle Yeme" in t):
        oglen_header = el
        break

    if oglen_header is None:
        raise RuntimeError("Öğle Yemeği Menüsü bölümü bulunamadı")

    # Başlığın üst container'ından menü kalemlerini topla
    container = oglen_header.find_parent()
    while container and not container.find_all(string=lambda t: t and t.strip() and t != oglen_header):
        container = container.find_parent()

    items = []
    if container:
        for sibling in container.find_all(["li", "div", "span", "p"]):
            text = sibling.get_text(strip=True)
            if text and text not in items and "ğle Yeme" not in text and len(text) > 2:
                items.append(text)

    return items


def build_email(items: list[str], date_str: str) -> tuple[str, str]:
    subject = f"🍽️ Bugünkü Öğle Yemeği Menüsü — {date_str}"

    html_items = "".join(f"<li>{item}</li>" for item in items)
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#c0392b;border-bottom:2px solid #c0392b;padding-bottom:8px">
        🍽️ Öğle Yemeği Menüsü
      </h2>
      <p style="color:#555">{date_str} · 12:00 / 20:00 / 00:00</p>
      <ul style="font-size:15px;line-height:2">{html_items}</ul>
      <p style="color:#aaa;font-size:12px;margin-top:24px">
        Bu e-posta otomatik olarak gönderilmiştir.
      </p>
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

    print("→ Portala giriş yapılıyor…")
    session = login()
    print("✓ Giriş başarılı")

    print("→ Menü çekiliyor…")
    items = fetch_menu(session)
    if not items:
        print("⚠ Menü bulunamadı, mail gönderilmedi.", file=sys.stderr)
        sys.exit(1)
    print(f"✓ {len(items)} kalem bulundu: {items}")

    subject, html, plain = build_email(items, today)
    send_email(subject, html, plain)


if __name__ == "__main__":
    main()
