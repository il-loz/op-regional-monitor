"""
Bot di monitoraggio per i Regional One Piece TCG - sezione Europe.
Quando trova nuovi eventi nella sezione "Europe", manda una notifica su Telegram.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============ CONFIGURAZIONE ============
URL = "https://en.onepiece-cardgame.com/events/regional-season1-26-27.html"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "INSERISCI_QUI_IL_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "INSERISCI_QUI_IL_CHAT_ID")
STATE_FILE = Path("known_events.json")
# ========================================

REGION_NAMES = {
    "north america", "europe", "oceania",
    "latin america", "asia", "middle east",
}


def fetch_europe_events():
    """Scarica la pagina ed estrae gli eventi della sezione Europe."""
    response = requests.get(URL, timeout=30, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Cerca su qualsiasi tipo di tag con testo "europe" (case-insensitive, normalizzato)
    europe_header = None
    for tag in soup.find_all(["h2", "h3", "h4", "h5", "h6", "dt", "strong", "b", "p", "div", "span"]):
        text = tag.get_text(strip=True).lower()
        if text == "europe":
            europe_header = tag
            break

    if not europe_header:
        print("DEBUG: header 'Europe' non trovato. Dump dei primi 30 heading:")
        for tag in soup.find_all(["h2", "h3", "h4", "h5", "h6"])[:30]:
            print(f"  <{tag.name}> {tag.get_text(strip=True)!r}")
        raise RuntimeError("Sezione 'Europe' non trovata nella pagina")

    print(f"DEBUG: trovato header 'Europe' come <{europe_header.name}>")
    europe_tag_name = europe_header.name

    # Iteriamo TUTTI gli elementi successivi del documento (non solo siblings).
    # Ci fermiamo quando troviamo un heading dello stesso tipo che e' un'altra regione.
    events = []
    current_organizer = None

    for el in europe_header.find_all_next():
        text = el.get_text(strip=True).lower() if el.name else ""

        # Stop: prossima regione
        if el.name == europe_tag_name and text in REGION_NAMES and text != "europe":
            break

        # Heading che NON e' una regione = nome organizzatore
        if el.name in ("h3", "h4", "h5", "h6") and text and text not in REGION_NAMES:
            current_organizer = el.get_text(strip=True)
            continue

        # <dl> dopo un organizzatore = dettagli evento
        if el.name == "dl" and current_organizer:
            full_text = el.get_text(" | ", strip=True)
            date_str = ""
            venue = ""
            m_date = re.search(r"Date:\s*([^|]+?)(?:\s*\||$)", full_text)
            if m_date:
                date_str = m_date.group(1).strip()
            m_venue = re.search(r"Venue:\s*([^|]+?)(?:\s*\||$)", full_text)
            if m_venue:
                venue = m_venue.group(1).strip()
            # Fallback: se non c'e' "Venue:" prendi il secondo dd
            if not venue:
                dds = el.find_all("dd")
                if len(dds) >= 2:
                    candidate = dds[1].get_text(" ", strip=True)
                    if "Date:" not in candidate and "Link:" not in candidate:
                        venue = candidate
            events.append({
                "organizer": current_organizer,
                "date": date_str,
                "venue": venue,
            })
            current_organizer = None

    return events


def make_event_key(event):
    return f"{event['organizer']}|{event['date']}"


def load_known():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_known(keys):
    STATE_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2))


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=30)
    r.raise_for_status()


def main():
    events = fetch_europe_events()
    print(f"Trovati {len(events)} eventi Europe sulla pagina.")
    for e in events:
        print(f"  - {e['organizer']} | {e['date']} | {e['venue']}")

    if len(events) == 0:
        print("ATTENZIONE: nessun evento trovato. Probabile cambio struttura HTML.")
        return

    known = load_known()
    new_events = [e for e in events if make_event_key(e) not in known]

    if not new_events:
        print("Nessun nuovo evento.")
        return

    if not known:
        print("Primo avvio: salvo gli eventi attuali senza notificare.")
        save_known({make_event_key(e) for e in events})
        return

    lines = [f"🏴‍☠️ <b>Nuovi Regional Europe trovati!</b> ({len(new_events)})\n"]
    for e in new_events:
        lines.append(f"• <b>{e['organizer']}</b>")
        lines.append(f"  📅 {e['date']}")
        if e['venue']:
            lines.append(f"  📍 {e['venue']}")
        lines.append("")
    lines.append(f"🔗 {URL}")
    send_telegram("\n".join(lines))
    print(f"Notificati {len(new_events)} nuovi eventi.")

    save_known({make_event_key(e) for e in events})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        sys.exit(1)
