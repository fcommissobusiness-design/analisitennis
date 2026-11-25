#!/usr/bin/env python3
"""Segnale AI: avvisa quando il canale "AI Assistant" di AnalisiTennis (GA4)
inizia a portare sessioni.

Il nodo strategico di AnalisiTennis: Google organico e' crollato e il sito non
ha ancora un canale AI (ChatGPT/Perplexity/Copilot) come PickForMe. Abbiamo
costruito il GEO (robots AI, llms.txt, FAQPage, IndexNow->Bing, guide profonde):
il pickup dei motori AI si misura in settimane sul canale "AI Assistant" di GA4.
Questo monitor interroga l'API GA4 Data per la property AnalisiTennis e, quando
compaiono le prime sessioni dal canale AI, STAMPA il segnale ed ESCE 1 -> la
GitHub Action fallisce e GitHub manda l'email automatica. E' il gemello GA4 di
backend/gsc_monitor.py (li' l'allarme e' un CROLLO, qui e' una BUONA notizia).

Credenziali: un service account Google con accesso in lettura alla property GA4,
passato come JSON in GA4_SA_JSON oppure (per riuso) in GSC_SA_JSON, o un file in
GA4_SA_FILE / GSC_SA_FILE. Senza credenziali NON fallisce: stampa il setup ed
esce 0 (nessun falso rosso prima che il setup sia completo).

Dipendenze (in CI): google-auth requests.
Uso locale:  GA4_SA_FILE=~/sa.json python3 ga4_ai_monitor.py
"""
from __future__ import annotations
import json, os, sys

# Property GA4 di AnalisiTennis (override via env GA4_PROPERTY_ID).
PROPERTY_ID = os.environ.get('GA4_PROPERTY_ID', '560566482')
GA4_API = f'https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY_ID}:runReport'
SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
LOOKBACK_DAYS = 7
MIN_AI_SESSIONS = 1   # appena compaiono sessioni AI, notifica

# Host degli assistenti AI: cattura anche il traffico che GA4 NON classifica
# come "AI Assistant" ma lascia in Referral/Unassigned.
AI_HOSTS = (
    'chatgpt.com', 'openai.com', 'perplexity.ai', 'gemini.google', 'bard.google',
    'copilot.microsoft', 'bing.com/chat', 'edgeservices.bing', 'claude.ai',
    'you.com', 'poe.com', 'phind.com', 'duckduckgo.com/chat',
)

SETUP = f"""\
[ga4-ai] NESSUNA CREDENZIALE (GA4_SA_JSON / GSC_SA_JSON / *_FILE assenti). Monitor in standby.
Setup una-tantum (lato Filippo, ~5 min; puoi RIUSARE il service account del monitor GSC):
  1. Prendi l'email del service account che usi per GSC (finisce in ...iam.gserviceaccount.com).
  2. console.cloud.google.com -> stesso progetto del service account -> abilita
     "Google Analytics Data API".
  3. analytics.google.com -> Amministrazione -> property "AnalisiTennis" ({PROPERTY_ID})
     -> Gestione accessi alla proprieta' -> aggiungi quell'email con ruolo "Visualizzatore".
  4. GitHub repo -> Settings -> Secrets and variables -> Actions:
     se riusi il service account GSC basta che il workflow passi GSC_SA_JSON (gia' fatto);
     altrimenti crea il secret GA4_SA_JSON col JSON del service account.
Da quel momento la Action ga4-ai-watch gira ogni settimana e manda email QUANDO il
canale AI inizia a portare sessioni (il segnale che aspettiamo)."""


def _load_creds():
    for var in ('GA4_SA_JSON', 'GSC_SA_JSON'):   # riusa lo stesso SA del monitor GSC
        raw = os.environ.get(var)
        if raw:
            try:
                return json.loads(raw)
            except Exception as e:
                print(f'[ga4-ai] {var} illeggibile: {e}', flush=True)
    for var in ('GA4_SA_FILE', 'GSC_SA_FILE'):
        p = os.environ.get(var)
        if p and os.path.exists(os.path.expanduser(p)):
            try:
                return json.loads(open(os.path.expanduser(p)).read())
            except Exception as e:
                print(f'[ga4-ai] {var} illeggibile: {e}', flush=True)
    return None


def _token(info):
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    creds.refresh(Request())
    return creds.token


def _run_report(token, dimension):
    import requests
    body = {
        'dateRanges': [{'startDate': f'{LOOKBACK_DAYS}daysAgo', 'endDate': 'today'}],
        'dimensions': [{'name': dimension}],
        'metrics': [{'name': 'sessions'}],
    }
    r = requests.post(GA4_API, headers={'Authorization': f'Bearer {token}'},
                      json=body, timeout=30)
    r.raise_for_status()
    out = []
    for row in r.json().get('rows', []):
        out.append((row['dimensionValues'][0]['value'], int(row['metricValues'][0]['value'])))
    return out


def main():
    info = _load_creds()
    if not info:
        print(SETUP, flush=True)
        return 0
    try:
        token = _token(info)
        ch_rows = _run_report(token, 'sessionDefaultChannelGroup')
        src_rows = _run_report(token, 'sessionSource')
    except Exception as e:
        print(f'[ga4-ai] errore API GA4: {e}', flush=True)
        print('  (un 403 significa che il service account non ha ancora accesso alla '
              'property GA4: completa il punto 3 del setup)', flush=True)
        return 0   # errore tecnico: non fallire (niente falso rosso)

    ai_channel = sum(v for d, v in ch_rows if 'ai assistant' in d.lower())
    ai_source = sum(v for d, v in src_rows if any(h in d.lower() for h in AI_HOSTS))
    total = sum(v for _, v in ch_rows)

    print(f'[ga4-ai] AnalisiTennis (property {PROPERTY_ID}), ultimi {LOOKBACK_DAYS} giorni:', flush=True)
    print(f'  sessioni totali: {total}', flush=True)
    for d, v in sorted(ch_rows, key=lambda x: -x[1]):
        print(f'    {d or "(not set)"}: {v}', flush=True)
    print(f'  -> canale "AI Assistant": {ai_channel} sessioni', flush=True)
    print(f'  -> sessioni da host AI (anche non categorizzati): {ai_source}', flush=True)
    if ai_source:
        for d, v in sorted(src_rows, key=lambda x: -x[1]):
            if any(h in d.lower() for h in AI_HOSTS):
                print(f'       {d}: {v}', flush=True)

    ai_total = max(ai_channel, ai_source)
    if ai_total >= MIN_AI_SESSIONS:
        print(f'\n[ga4-ai] 🟢 CANALE AI ATTIVO: {ai_total} sessioni da AI negli ultimi '
              f'{LOOKBACK_DAYS} giorni. Il pickup dei motori AI e\' iniziato: e\' il '
              f'segnale che aspettavamo dopo il lavoro GEO.', flush=True)
        return 1   # exit!=0 -> email GitHub (buona notizia: il canale AI si e' acceso)
    print('\n[ga4-ai] canale AI ancora a zero: nessuna notifica, si continua a monitorare.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
