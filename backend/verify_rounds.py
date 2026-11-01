"""Verifica via WEB CHECK la fase reale di ogni torneo della slate, per
confermare o SMENTIRE il campo `tournament_round` di API Tennis, che e'
inaffidabile: segna "Final" a tanti match dello stesso torneo nello stesso
giorno e non distingue bene i turni. Il web check (claude headless con web
search, la stessa infrastruttura delle analisi) e' la fonte di verita'.

Logica (un check per TORNEO, non per match: la fase del torneo oggi vale per
tutti i suoi match):
  1. Si interroga il web: "nel torneo X, in data Y, quale turno del tabellone
     principale si gioca? E' il giorno delle qualificazioni?".
  2. Se il web dice QUALIFICAZIONE -> i match di quel torneo vengono RIMOSSI
     dalla slate (non copriamo le quali).
  3. Se il web da' un turno con buona confidenza -> quel turno SOVRASCRIVE il
     round API, cosi' l'analisi descrive la fase giusta.
  4. Se il web e' incerto: un solo match del torneo con round "finale" si tiene
     (finale plausibile, es. Challenger di domenica); piu' match "finale" nello
     stesso torneo senza conferma -> il round viene NEUTRALIZZATO (il modello
     non inventa "finale").
  5. Un torneo con piu' di una "finale" e web incerto e' il segnale classico di
     dato corrotto: in dubbio si neutralizza il round, non si afferma la finale.

Robusto: su errore o timeout del web check, il torneo resta invariato (nessun
blocco della pipeline), ma un torneo con piu' "finali" viene comunque
neutralizzato in prudenza.

Uso:  python3 verify_rounds.py selected_YYYY-MM-DD.json
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from generate_analysis import _claude_call, _oggi

# Mappa fase canonica -> etichetta round italiana leggibile per il prompt analisi.
ROUND_IT = {
    'finale': 'Finale',
    'semifinale': 'Semifinale',
    'quarti': 'Quarti di finale',
    'ottavi': 'Ottavi di finale',
    'sedicesimi': 'Sedicesimi di finale',
    'primo turno': 'Primo turno',
    'secondo turno': 'Secondo turno',
}


def _circuito(m):
    tipo = (m.get('event_type_type') or '').lower()
    nome = (m.get('tournament_name') or '').lower()
    if 'wta' in tipo or 'wta' in nome:
        return 'WTA'
    if 'challenger' in tipo or 'challenger' in nome:
        return 'ATP Challenger'
    return 'ATP'


def _ha_finale(matches):
    def _is_fin(r):
        r = (r or '').lower()
        return 'final' in r and not any(x in r for x in ('semi', 'quarter', '1/', 'qualif'))
    return [m for m in matches if _is_fin(m.get('tournament_round'))]


def verifica_torneo(nome, circuito, data_iso, giocatori):
    """Web check della fase reale del torneo in quella data. Ritorna dict o None."""
    nome_pulito = re.sub(r'\s*-\s*qualification$', '', nome, flags=re.I).strip()
    prompt = (
        f"Fai una WEB SEARCH accurata e stabilisci, per il torneo di tennis "
        f"{circuito} di {nome_pulito}, in data {data_iso}, QUALE turno del "
        f"tabellone principale di singolare si gioca quel giorno. "
        f"Giocatori dati in programma quel giorno: {', '.join(giocatori[:8])}. "
        f"Stabilisci anche se quel giorno si giocano le QUALIFICAZIONI del torneo. "
        f"Se non trovi una conferma chiara da fonti affidabili, usa confidenza "
        f"'bassa'. NON tirare a indovinare. Rispondi SOLO con questo JSON:\n"
        f'{{"fase": "finale|semifinale|quarti|ottavi|sedicesimi|primo turno|secondo turno|qualificazione|sconosciuto", '
        f'"is_qualificazione": true, "confidenza": "alta|media|bassa", "fonte": "url"}}'
    )
    try:
        r = _claude_call(prompt, timeout=240)
        if isinstance(r, dict) and 'fase' in r:
            return r
    except Exception as e:
        print(f'  [errore web check] {nome_pulito}: {e}', flush=True)
    return None


def processa(matches):
    data_iso = _oggi().isoformat()
    gruppi = defaultdict(list)
    for m in matches:
        gruppi[m.get('tournament_name') or '?'].append(m)

    tieni = []
    for torneo, ms in gruppi.items():
        giocatori = []
        for m in ms:
            giocatori += [m.get('event_first_player', ''), m.get('event_second_player', '')]
        circ = _circuito(ms[0])
        res = verifica_torneo(torneo, circ, data_iso, giocatori)
        finali = _ha_finale(ms)

        if res is None:
            # Web non disponibile: prudenza. Piu' "finali" nello stesso torneo =
            # dato corrotto -> neutralizza; altrimenti lascia com'e'.
            if len(finali) > 1:
                for m in ms:
                    m['tournament_round'] = 'Tabellone principale'
                print(f"  [{torneo}] web n/d, {len(finali)} 'finali' -> round neutralizzato (prudenza)", flush=True)
            tieni += ms
            continue

        fase = (res.get('fase') or '').strip().lower()
        qual = bool(res.get('is_qualificazione')) or fase == 'qualificazione'
        conf = (res.get('confidenza') or 'bassa').strip().lower()

        if qual:
            print(f"  [{torneo}] WEB: qualificazione -> {len(ms)} match RIMOSSI", flush=True)
            continue

        if fase in ROUND_IT and conf in ('alta', 'media'):
            for m in ms:
                m['tournament_round'] = ROUND_IT[fase]
            print(f"  [{torneo}] WEB: {ROUND_IT[fase]} (conf {conf}) -> round corretto", flush=True)
            tieni += ms
            continue

        # Web incerto (sconosciuto o confidenza bassa).
        if len(finali) > 1:
            for m in ms:
                m['tournament_round'] = 'Tabellone principale'
            print(f"  [{torneo}] web incerto + {len(finali)} 'finali' -> round neutralizzato", flush=True)
        else:
            print(f"  [{torneo}] web incerto, dato API plausibile -> invariato", flush=True)
        tieni += ms

    return tieni


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: python3 verify_rounds.py selected_YYYY-MM-DD.json', file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    matches = json.loads(path.read_text())
    print(f'[verify_rounds] {len(matches)} match, verifica web per torneo...', flush=True)
    tenuti = processa(matches)
    path.write_text(json.dumps(tenuti, indent=2, ensure_ascii=False))
    print(f'[verify_rounds] {len(tenuti)}/{len(matches)} match confermati (round verificati via web)', flush=True)
