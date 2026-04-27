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

    # Trova l'intestazione "Europe"
    europe_header = None
    for tag in soup.find_all(["h4", "h5", "h3"]):
        if tag.get_text(strip=True).lower() == "europe":
            europe_header = tag
            break

    if not europe_header:
        raise RuntimeError("Sezione 'Europe' non trovata nella pagina")

    # Raccoglie tutti gli h5 (organizzatori) tra "Europe" e la prossima regione
    next_regions = {"oceania", "latin america", "north america", "asia", "middle east"}
    events = []
    current = europe_header.find_next_sibling()
    while current is not None:
        text = current.get_text(strip=True).lower()
        # Stop quando inizia un'altra regione
        if current.name in ("h4", "h5") and text in next_regions:
            break
        if current.name == "h5":
            organizer = current.get_text(strip=True)
            # Cerca data e venue nel <dl> successivo
            dl = current.find_next_sibling("dl")
            date_str, venue = "", ""
            if dl:
                dds = dl.find_all("dd")
                full_text = " | ".join(dd.get_text(" ", strip=True) for dd in dds)
                m_date = re.search(r"Date:\s*([^|]+)", full_text)
                if m_date:
                    date_str = m_date.group(1).strip()
                m_venue = re.search(r"Venue:\s*([^|]+)", full_text)
                if m_venue:
                    venue = m_venue.group(1).strip()
            events.append({
                "organizer": organizer,
                "date": date_str,
                "venue": venue,
            })
        current = current.find_next_sibling()

    return events


def make_event_key(event):
    """Chiave univoca per riconoscere un evento (organizzatore + data)."""
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

    known = load_known()
    new_events = [e for e in events if make_event_key(e) not in known]

    if not new_events:
        print("Nessun nuovo evento.")
        return

    # Primo avvio: salva tutto senza notificare (evita spam con tutti gli eventi gia' presenti)
    if not known:
        print("Primo avvio: salvo gli eventi attuali senza notificare.")
        save_known({make_event_key(e) for e in events})
        return

    # Costruisci messaggio
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

    # Aggiorna lo stato
    save_known({make_event_key(e) for e in events})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        # Se vuoi essere notificato anche degli errori, decommentare:
        # try: send_telegram(f"⚠️ Errore nel monitor OP TCG: {e}")
        # except: pass
        sys.exit(1)
