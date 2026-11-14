#!/usr/bin/env python3
"""Allarme precoce GSC: becca un tuffo di impressioni Google stile-04/10 in
GIORNI, non settimane (fu quello il costo vero della penalty su PickForMe:
restare piatti a zero per settimane prima di accorgersene).

Interroga l'API Search Analytics di Search Console per sc-domain:analisitennis.it,
confronta la finestra RECENTE con la BASELINE immediatamente precedente e, se le
impressioni crollano oltre soglia, STAMPA l'allarme ed ESCE 1. Pensato per girare
ogni giorno in una GitHub Action schedulata: l'exit!=0 fa partire l'email
automatica di GitHub (stesso meccanismo del deploy health-check).

GSC ha ~2-3 giorni di lag, quindi:
  RECENTE  = media impressioni dei giorni [3..5] fa
  BASELINE = media impressioni dei giorni [6..14] fa
Allarme se RECENTE < BASELINE * (1 - DROP) con BASELINE abbastanza alta da non
dare falsi positivi sul rumore.

Credenziali: un service account Google con accesso alla proprieta' GSC, passato
come JSON nell'env GSC_SA_JSON (secret GitHub) oppure in un file indicato da
GSC_SA_FILE. Senza credenziali NON fallisce: stampa le istruzioni di setup ed
esce 0 (cosi' la Action non da' falsi rossi prima che Filippo completi il setup).

Dipendenze (in CI): google-auth requests.
Uso locale:  GSC_SA_FILE=~/sa.json python3 gsc_monitor.py
"""
from __future__ import annotations
import json, os, sys, datetime

SITE = 'sc-domain:analisitennis.it'
DROP = 0.50            # calo impressioni oltre il 50% = allarme
MIN_BASELINE = 300     # impressioni/giorno minime in baseline per valutare (anti rumore)
SETUP = """\
[gsc-monitor] NESSUNA CREDENZIALE (GSC_SA_JSON / GSC_SA_FILE assente). Monitor in standby.
Setup una-tantum (lato Filippo, ~5 min):
  1. console.cloud.google.com -> crea/scegli un progetto -> abilita "Google Search Console API".
  2. IAM & Admin -> Service Accounts -> crea un service account -> Keys -> Add key (JSON) -> scarica.
  3. search.google.com/search-console -> proprieta' sc-domain:analisitennis.it -> Impostazioni ->
     Utenti e autorizzazioni -> Aggiungi l'email del service account (ruolo: Con limitazioni/Full).
  4. GitHub repo -> Settings -> Secrets and variables -> Actions -> New secret:
     nome GSC_SA_JSON, valore = contenuto del file JSON scaricato.
Da quel momento la Action gsc-watch gira ogni giorno e manda email solo se le impressioni crollano."""


def _load_creds():
    raw = os.environ.get('GSC_SA_JSON')
    if not raw and os.environ.get('GSC_SA_FILE'):
        p = os.path.expanduser(os.environ['GSC_SA_FILE'])
        if os.path.exists(p):
            raw = open(p).read()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception as e:
        print(f'[gsc-monitor] credenziali illeggibili: {e}', flush=True)
        return None


def _query(info):
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=['https://www.googleapis.com/auth/webmasters.readonly'])
    sess = AuthorizedSession(creds)
    end = datetime.date.today()
    start = end - datetime.timedelta(days=16)
    url = f'https://searchconsole.googleapis.com/webmasters/v3/sites/{SITE.replace(":", "%3A").replace("/", "%2F")}/searchAnalytics/query'
    body = {'startDate': start.isoformat(), 'endDate': end.isoformat(),
            'dimensions': ['date'], 'rowLimit': 100}
    r = sess.post(url, json=body, timeout=60)
    r.raise_for_status()
    rows = r.json().get('rows', [])
    # {date: impressions}
    return {row['keys'][0]: row.get('impressions', 0) for row in rows}


def main():
    info = _load_creds()
    if not info:
        print(SETUP, flush=True)
        sys.exit(0)
    try:
        by_day = _query(info)
    except Exception as e:
        print(f'[gsc-monitor] query fallita ({type(e).__name__}: {e}); non segnalo per non dare falsi allarmi.', flush=True)
        sys.exit(0)

    today = datetime.date.today()
    def avg(a, b):  # media impressioni per i giorni da a a b fa (inclusi)
        vals = [by_day.get((today - datetime.timedelta(days=d)).isoformat(), 0) for d in range(a, b + 1)]
        return sum(vals) / len(vals) if vals else 0.0

    recent = avg(3, 5)      # finestra recente (oltre il lag GSC)
    baseline = avg(6, 14)   # baseline precedente

    print(f'[gsc-monitor] impressioni/gg -> recente(3-5gg fa)={recent:.0f}  baseline(6-14gg fa)={baseline:.0f}', flush=True)

    if baseline < MIN_BASELINE:
        print(f'[gsc-monitor] baseline sotto {MIN_BASELINE}/gg: volume troppo basso per un giudizio affidabile, nessun allarme.', flush=True)
        sys.exit(0)

    if recent < baseline * (1 - DROP):
        calo = (1 - recent / baseline) * 100 if baseline else 0
        print(f'[gsc-monitor] 🔴 ALLARME: impressioni Google -{calo:.0f}% (recente {recent:.0f} vs baseline {baseline:.0f}).', flush=True)
        print('[gsc-monitor] Possibile penalty/crollo stile-04/10. Controllare GSC: Azioni manuali, Indicizzazione, Rendimento. Vedi memoria crollo-gsc.', flush=True)
        sys.exit(1)

    print('[gsc-monitor] OK: nessun crollo di impressioni Google.', flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
