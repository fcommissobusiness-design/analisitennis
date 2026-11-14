#!/usr/bin/env python3
"""Audit permanente dei contenuti pubblicati di AnalisiTennis.

Nato il 4 novembre 2026, dopo che un lettore ha segnalato alla redazione che il
profilo di Weronika Falkowska la descriveva mancina quando e' destra. Il
controllo che ne e' seguito ha trovato decine di errori della stessa famiglia,
tutti prodotti da generatori che scrivevano senza ancoraggio ai dati.

Questo script ripete da solo, in pochi secondi e senza chiamate a pagamento,
tutti i controlli incrociati fatti a mano quel giorno. Non sostituisce il
fact-check sulle fonti: intercetta le CONTRADDIZIONI INTERNE e i difetti
sistematici, che sono il sintomo piu' affidabile di un'allucinazione.

Uso:
    python3 audit_fatti.py            # report completo
    python3 audit_fatti.py --silenzioso   # solo il riepilogo
Codice di uscita: 0 se pulito, 1 se ci sono problemi bloccanti.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / 'src' / 'content' / 'articoli'
GIOC = ROOT / 'src' / 'content' / 'giocatori-profilo'
TORN = ROOT / 'src' / 'content' / 'tornei-profilo'
GUIDE = ROOT / 'src' / 'content' / 'guide'

_FM = re.compile(r'^---\n(.*?)\n---\n(.*)$', re.S)


def leggi(p: Path):
    t = p.read_text(encoding='utf-8')
    m = _FM.match(t)
    return (m.group(1), m.group(2)) if m else ('', t)


def campo(fm: str, k: str):
    m = re.search(rf'^{k}:\s*"?(.*?)"?\s*$', fm, re.M)
    return m.group(1).strip() if m and m.group(1).strip() else None


def norm(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


class Audit:
    def __init__(self):
        self.gravi: list[str] = []      # bloccanti: contraddizioni factuali
        self.avvisi: list[str] = []     # da guardare: qualita' e deperibilita'
        self.note: list[str] = []       # informativi

    def grave(self, s): self.gravi.append(s)
    def avviso(self, s): self.avvisi.append(s)
    def nota(self, s): self.note.append(s)


def carica_profili():
    giocatori, tornei = {}, {}
    for p in sorted(GIOC.glob('*.md')):
        fm, body = leggi(p)
        if (campo(fm, 'pubblicato') or '').lower() == 'false':
            continue
        giocatori[p.stem] = {
            'file': p.name, 'nome': campo(fm, 'nome'), 'mano': campo(fm, 'mano'),
            'rovescio': campo(fm, 'rovescio'), 'nazionalita': campo(fm, 'nazionalita'),
            'categoria': campo(fm, 'categoria'), 'fm': fm, 'body': body,
        }
    for p in sorted(TORN.glob('*.md')):
        fm, body = leggi(p)
        if (campo(fm, 'pubblicato') or '').lower() == 'false':
            continue
        tornei[p.stem] = {
            'file': p.name, 'nome': campo(fm, 'nome'), 'citta': campo(fm, 'citta'),
            'superficie': campo(fm, 'superficie'), 'categoria': campo(fm, 'categoria'),
            'fm': fm, 'body': body,
        }
    return giocatori, tornei


def controlla(a: Audit):
    giocatori, tornei = carica_profili()
    articoli = sorted(ART.glob('*.md'))
    a.nota(f'{len(articoli)} articoli, {len(giocatori)} profili giocatore, '
           f'{len(tornei)} profili torneo, {len(list(GUIDE.glob("*.md")))} guide')

    # --- 1. Mancinismo negli articoli contro i profili verificati -----------
    per_cognome = {}
    for slug, d in giocatori.items():
        if d['nome'] and d['mano']:
            per_cognome[norm(d['nome'].split()[-1])] = (d['nome'], d['mano'])
    # Si segnala solo l'APPOSIZIONE DIRETTA ("Rossi, mancino", "il mancino
    # Rossi"), non la semplice vicinanza nella frase: in un pezzo su due
    # giocatori la frase "dare a Basilashvili un riferimento su come gestire
    # gli scambi contro il mancino austriaco" nomina il destro e il mancino
    # nella stessa riga, e un controllo per prossimita' urlerebbe al falso.
    APPOSIZIONE = re.compile(
        r"\*{0,2}([A-ZÀ-Ý][a-zà-ÿ]{3,18})\*{0,2}[,\s]+(?:(?:è|e')\s*)?"
        r'(?:un[oa]?\s+|il\s+|la\s+)?mancin[oa]\b'
        r'|(?:il|la)\s+mancin[oa]\s+\*{0,2}([A-ZÀ-Ý][a-zà-ÿ]{3,18})')
    for p in articoli:
        fm, body = leggi(p)
        for m in APPOSIZIONE.finditer(body):
            cog = norm(m.group(1) or m.group(2) or '')
            if cog in per_cognome:
                nome, mano = per_cognome[cog]
                if 'mancin' not in mano:
                    a.grave(f'{p.name}: descrive {nome} come mancino, ma il profilo '
                            f'verificato dice "{mano}"')

    # --- 2. Superficie dell'articolo contro il torneo verificato ------------
    per_citta = {norm(d['citta']): d for d in tornei.values() if d['citta']}
    per_nome = {norm(d['nome']): d for d in tornei.values() if d['nome']}
    # Indice per SLUG del profilo (lo stem del file, es. 'stockholm-2026' ->
    # 'stockholm', 'hersonissos-3-2026' -> 'hersonissos 3', 'finals-indian-
    # wells-2026' -> 'finals indian wells'). Lo slug nasce dal nome grezzo del
    # torneo com'e' scritto negli articoli (nome inglese + numero di edizione),
    # quindi aggancia i casi che la citta' italiana ("Stoccolma") o il nome
    # ufficiale ("Bybit Stockholm Open") da soli non intercettano.
    def _slug_key(stem):
        return norm(re.sub(r'-20\d\d$', '', stem).replace('-', ' '))
    per_slug = {_slug_key(stem): d for stem, d in tornei.items()}
    alias = {'basel': 'basilea', 'paris': 'parigi', 'brussels': 'bruxelles',
             'lisbon': 'lisbona', 'florence': 'firenze', 'lyon': 'lione',
             'queretaro': 'santiago de queretaro'}
    senza_profilo = Counter()
    for p in articoli:
        fm, _ = leggi(p)
        tor = campo(fm, 'torneo')
        sup = campo(fm, 'superficie')
        if not tor or tor == 'Editoriale':
            continue
        base = re.sub(r'\s*-\s*Qualification\s*$', '', tor, flags=re.I)
        base = re.sub(r'\s*\([^)]*\)\s*$', '', base).strip()
        k = norm(base)
        d = (per_citta.get(alias.get(k, k)) or per_citta.get(k)
             or per_nome.get(k) or per_slug.get(k))
        if not d:
            senza_profilo[tor] += 1
            continue
        if sup and d['superficie'] and sup != d['superficie']:
            a.grave(f'{p.name}: dichiara superficie "{sup}" ma il profilo verificato '
                    f'di {d["nome"]} dice "{d["superficie"]}"')
    for tor, n in senza_profilo.items():
        a.avviso(f'torneo "{tor}" senza profilo verificato: {n} articoli '
                 f'pubblicati senza riscontro su superficie e categoria')

    # --- 3. Attributi affermati in prosa ma non in frontmatter --------------
    for slug, d in giocatori.items():
        if not d['mano'] and re.search(r'\bmancin[oa]\b|\bdestrors[oa]\b|'
                                       r'\bmano (sinistra|destra)\b', d['body'], re.I):
            a.grave(f'{d["file"]}: il testo parla della mano del giocatore ma il campo '
                    f'`mano` e\' assente, quindi il dato non e\' verificato')
        if not d['rovescio'] and re.search(r'rovescio (a )?(una mano|bimane|a due mani)',
                                           d['body'], re.I):
            a.avviso(f'{d["file"]}: il testo descrive il tipo di rovescio ma il campo '
                     f'`rovescio` e\' assente')

    # --- 4. Contenuto deperibile nei profili --------------------------------
    for slug, d in giocatori.items():
        if re.search(r'^##\s*Il momento\s*$', d['body'], re.M):
            a.avviso(f'{d["file"]}: contiene la sezione deperibile "Il momento", '
                     f'che invecchia male e torna falsa da sola')
        if re.search(r'\b(bilancio|ruolino) (di |recente )?(di )?[a-z]+ vittorie e',
                     d['body'], re.I):
            a.avviso(f'{d["file"]}: cita un bilancio stagionale di vittorie e sconfitte, '
                     f'dato deperibile')

    # --- 5. Profili pubblicati ma non identificabili ------------------------
    for slug, d in giocatori.items():
        nome = d['nome'] or ''
        if re.fullmatch(r'[A-Z]\.( [A-Z]\.)* ?[A-Za-zÀ-ÿ\'-]+', nome.strip()):
            a.grave(f'{d["file"]}: pubblicato con nome non risolto "{nome}". '
                    f'Una testata non pubblica schede su persone non identificate')

    # --- 6. Tipografia ------------------------------------------------------
    ascii_apo = Counter()
    em_dash = Counter()
    SALTA = {"ATP'", "WTA'", "ITF'", "Slam'", "Masters'", "Challenger'", "po'",
             "cemento'", "erba'", "terra'", "indoor'", "profilo'", "Arena'",
             "da'", "men'", "com'", "mezz'", "prim'", "trent'", "vent'", "Queen'",
             "quarant'", "ventiquattr'", "content'", "tocco'", "ripete'", "Lu'",
             "AnalisiTennis'", "Women'", "Wen'", "Shapovalov'"}
    ELISIONI = re.compile(
        r"^(l|all|dell|dall|nell|sull|un|d|c|tutt|quell|quest|anch|sant|grand|"
        r"bell|senz|dov|n|s|t|m|v|gl|agl|negl|dagl|sugl|coll|nessun|alcun|"
        r"ciascun|buon|L|All|Dell|Dall|Nell|Sull|Un|D|C|Tutt|Quell|Quest|Anch|"
        r"E|Nessun|Com)'$")
    for d in (ART, GIOC, TORN, GUIDE):
        for p in d.glob('*.md'):
            t = p.read_text(encoding='utf-8')
            if '—' in t:
                em_dash[p.name] = t.count('—')
            for tok in re.findall(r"[A-Za-zÀ-ÿ]+'", t):
                if tok not in SALTA and not ELISIONI.match(tok):
                    ascii_apo[p.name] += 1
    if ascii_apo:
        a.avviso(f'{sum(ascii_apo.values())} apostrofi ASCII al posto delle lettere '
                 f'accentate, in {len(ascii_apo)} file (es. {list(ascii_apo)[:3]})')
    if em_dash:
        a.avviso(f'{sum(em_dash.values())} trattini lunghi (vietati dallo stile) '
                 f'in {len(em_dash)} file (es. {list(em_dash)[:3]})')

    # --- 7. Lessico da scommesse (il sito e' una testata, non un tipster) ---
    # Attenzione ai falsi amici: in italiano "quota" e' anche l'altitudine
    # ("la terra in quota di Queretaro"), "quotato" vuol dire stimato
    # ("avversari piu' quotati") e "puntata" e' anche l'episodio di una serie.
    # Qui cerchiamo solo i termini inequivocabili, e saltiamo le occorrenze
    # negate, perche' la riga editoriale del sito dice proprio di scrivere
    # "senza quote, senza linguaggio da scommesse".
    # "quota" entra solo se accompagnata da un numero, cioe' quando e' davvero
    # una quota da bookmaker e non l'altitudine di Queretaro o di Cali.
    VIETATE = re.compile(r'\b(bookmaker|schedina|multipla|value bet|stake|'
                         r'scommess\w*|quot[ae] (a |di )?\d)', re.I)
    NEGATA = re.compile(r'(senza|nessun\w*|niente|mai|non|anziche|invece di)\s+'
                        r'[\w\s,]{0,30}$', re.I)
    for d in (ART, GIOC, TORN, GUIDE):
        for p in d.glob('*.md'):
            t = p.read_text(encoding='utf-8')
            colpiti = []
            for m in VIETATE.finditer(t):
                if NEGATA.search(t[max(0, m.start() - 40):m.start()]):
                    continue  # "senza quote", "niente scommesse": e' la nostra linea
                colpiti.append(m.group(0).lower())
            if colpiti:
                a.grave(f'{p.name}: lessico da scommesse ({sorted(set(colpiti))[:3]}), '
                        f'incompatibile con una testata editoriale')

    # --- 8. Articoli senza fact-check registrato ----------------------------
    analisi = Path(__file__).resolve().parent / 'analyses'
    if analisi.exists():
        senza = 0
        for f in analisi.glob('analysis_*.json'):
            try:
                d = json.loads(f.read_text())
            except Exception:
                senza += 1
                continue
            if not (d.get('fact_check') or {}).get('verdict'):
                senza += 1
        if senza:
            a.avviso(f'{senza} analisi senza verdetto di fact-check registrato: '
                     f'sono articoli mai passati dal gate')

    # --- 9. Pertinenza delle copertine --------------------------------------
    riuso = defaultdict(list)
    for p in articoli:
        fm, _ = leggi(p)
        cred = campo(fm, 'cover_credit')
        if cred:
            riuso[cred.split('|')[0].strip()].append(p.name)
    molte = {k: v for k, v in riuso.items() if len(v) >= 3}
    if molte:
        a.avviso(f'{len(molte)} immagini di copertina riusate da 3 o piu\' articoli '
                 f'(la piu\' ripetuta: {max(molte, key=lambda k: len(molte[k]))[:50]})')
    SOSPETTI = ('box', 'crowd', 'spectat', 'practice', 'skyline', 'panorama', 'scoreboard')
    fuoritema = [p.name for p in articoli
                 if (lambda c: c and any(s in c.lower() for s in SOSPETTI))(
                     campo(leggi(p)[0], 'cover_credit'))]
    if fuoritema:
        a.avviso(f'{len(fuoritema)} copertine con soggetto potenzialmente fuori tema '
                 f'(pubblico, allenamenti, panoramiche): es. {fuoritema[:2]}')


def main():
    silenzioso = '--silenzioso' in sys.argv
    a = Audit()
    controlla(a)
    if not silenzioso:
        for titolo, voci in (('PROBLEMI GRAVI', a.gravi), ('DA GUARDARE', a.avvisi)):
            if voci:
                print(f'\n=== {titolo} ({len(voci)}) ===')
                for v in voci:
                    print(f'  - {v}')
    for n in a.note:
        print(f'\n{n}')
    print(f'\nRIEPILOGO: {len(a.gravi)} problemi gravi, {len(a.avvisi)} da guardare.')
    if a.gravi:
        print('ESITO: NON PULITO. I problemi gravi sono contraddizioni factuali '
              'fra contenuti pubblicati e vanno risolte prima di pubblicare altro.')
        return 1
    print('ESITO: pulito sui controlli automatici.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
