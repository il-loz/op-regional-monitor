"""
Bot di monitoraggio per i Regional One Piece TCG - sezione Europe.
- Notifica su Telegram quando trova nuovi eventi
- Mantiene un messaggio riassunto sempre aggiornato con la lista completa
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
SUMMARY_FILE = Path("summary_message.json")  # memorizza l'ID del messaggio riassunto
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

    events = []
    current_organizer = None

    for el in europe_header.find_all_next():
        text = el.get_text(strip=True).lower() if el.name else ""

        if el.name == europe_tag_name and text in REGION_NAMES and text != "europe":
            break

        if el.name in ("h3", "h4", "h5", "h6") and text and text not in REGION_NAMES:
            current_organizer = el.get_text(strip=True)
            continue

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
    """Chiave univoca: include anche il luogo per renderlo leggibile nel file."""
    parts = [event['organizer'], event['date']]
    if event.get('venue'):
        venue_short = event['venue'][:60].rstrip()
        parts.append(venue_short)
    return "|".join(parts)


def load_known():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_known(keys):
    STATE_FILE.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2))


def load_summary_id():
    if SUMMARY_FILE.exists():
        return json.loads(SUMMARY_FILE.read_text()).get("message_id")
    return None


def save_summary_id(message_id):
    SUMMARY_FILE.write_text(json.dumps({"message_id": message_id}, indent=2))


# ---------- Telegram helpers ----------

def telegram_request(method, data):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()


def send_telegram(message):
    """Manda un nuovo messaggio. Ritorna il message_id."""
    result = telegram_request("sendMessage", {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })
    return result["result"]["message_id"]


def edit_telegram(message_id, message):
    """Modifica un messaggio esistente. Ritorna True se ok, False se il messaggio non esiste piu'."""
    try:
        telegram_request("editMessageText", {
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        return True
    except requests.HTTPError as e:
        # Telegram restituisce 400 se il messaggio non esiste piu' o e' identico
        body = e.response.text if e.response is not None else ""
        if "message is not modified" in body:
            # Contenuto identico, non e' un errore
            return True
        print(f"Impossibile modificare il messaggio {message_id}: {body}")
        return False


# ---------- Costruzione messaggi ----------

def build_summary_message(events):
    """Messaggio riassunto con la lista completa degli eventi."""
    from datetime import datetime, timezone, timedelta
    # Ora italiana (CET/CEST approssimato come UTC+1, va bene per un timestamp)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    timestamp = now.strftime("%d/%m/%Y %H:%M")

    lines = [
        f"🏴‍☠️ <b>Regional Europe – Stagione 26/27</b>",
        f"<i>Aggiornato: {timestamp}</i>",
        "",
        f"<b>{len(events)} eventi attualmente in programma:</b>",
        "",
    ]
    for e in events:
        lines.append(f"• <b>{e['organizer']}</b>")
        lines.append(f"  📅 {e['date']}")
        if e['venue']:
            lines.append(f"  📍 {e['venue']}")
        lines.append("")
    lines.append(f"🔗 <a href=\"{URL}\">Pagina ufficiale</a>")
    return "\n".join(lines)


def build_new_events_message(new_events):
    """Notifica per i nuovi eventi appena scoperti."""
    lines = [f"🆕 <b>Nuovi Regional Europe!</b> ({len(new_events)})\n"]
    for e in new_events:
        lines.append(f"• <b>{e['organizer']}</b>")
        lines.append(f"  📅 {e['date']}")
        if e['venue']:
            lines.append(f"  📍 {e['venue']}")
        lines.append("")
    lines.append(f"🔗 {URL}")
    return "\n".join(lines)


# ---------- Logica principale ----------

def update_summary(events):
    """Crea o aggiorna il messaggio riassunto pinnato."""
    summary_text = build_summary_message(events)
    summary_id = load_summary_id()

    if summary_id is not None:
        # Prova ad aggiornare il messaggio esistente
        if edit_telegram(summary_id, summary_text):
            print(f"Messaggio riassunto aggiornato (id={summary_id}).")
            return
        # Se non riesce (es. messaggio cancellato), ricreiamo
        print("Messaggio riassunto non piu' modificabile, ne creo uno nuovo.")

    # Crea un nuovo messaggio riassunto
    new_id = send_telegram(summary_text)
    save_summary_id(new_id)
    print(f"Creato nuovo messaggio riassunto (id={new_id}). PINNALO in chat!")


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
    summary_id = load_summary_id()

    # Caso 1: primo avvio - creo il messaggio riassunto e salvo lo stato,
    # senza mandare notifica di "novita'"
    if not known:
        print("Primo avvio: creo il messaggio riassunto e salvo gli eventi attuali.")
        update_summary(events)
        save_known({make_event_key(e) for e in events})
        return

    # Caso 2: il messaggio riassunto non esiste ancora (es. prima esecuzione
    # dopo aver cambiato chat o aver perso lo stato). Lo creo senza
    # mandare notifica di novita'.
    if summary_id is None:
        print("Messaggio riassunto mancante: lo creo senza notifica di novita'.")
        update_summary(events)
        # Allineo anche known_events giusto per sicurezza
        save_known({make_event_key(e) for e in events})
        return

    # Caso 3: nessuna novita' - non tocco niente, nessun messaggio inviato/modificato
    if not new_events:
        print("Nessun nuovo evento. Non invio ne' modifico messaggi.")
        return

    # Caso 4: ci sono novita' - aggiorno il riassunto E mando notifica separata
    update_summary(events)
    send_telegram(build_new_events_message(new_events))
    print(f"Notificati {len(new_events)} nuovi eventi.")

    save_known({make_event_key(e) for e in events})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        sys.exit(1)
