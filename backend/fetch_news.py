"""Newsroom AnalisiTennis: scopre, VERIFICA e scrive le notizie di tennis.

Principio fondante: una notizia si SCOPRE da fonti reali e si VERIFICA, non si
genera. Ogni fatto deve venire da ricerca web con URL reali, essere confermato
da un secondo passaggio indipendente (>=2 fonti, o una ufficiale) e superare il
gate anti-allucinazione prima di essere pubblicato. Meglio nessuna notizia che
una falsa.

Flusso: scoperta -> (per ogni candidata) verifica -> scrittura ancorata al
fatto verificato -> gate -> salvataggio. Idempotente: non ripubblica notizie
gia' presenti (dedup per chiave categoria+entita+data).

Uso: python3 fetch_news.py [YYYY-MM-DD]
Disattivabile a monte: se ANALISITENNIS_NEWS=0 esce subito.
"""
from __future__ import annotations
import json
import os
import re
import sys
import shutil
import subprocess
import unicodedata
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEWS_DIR = ROOT / 'src' / 'content' / 'news'
NEWS_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIE = [
    'cambio-allenatore', 'infortunio', 'forfait', 'ritiro-carriera',
    'titolo', 'traguardo', 'squalifica', 'wild-card', 'rientro', 'altro',
]


def _now_rome():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Europe/Rome'))
    except Exception:
        return datetime.now()


def _slugify(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^\w\s-]', '', s.lower())
    s = re.sub(r'[\s_-]+', '-', s).strip('-')
    return s[:70]


# --- Normalizzazione tipografica (stesse regole degli articoli) ---
_ACUTE_E = {'perche': 'perché', 'poiche': 'poiché', 'finche': 'finché',
            'affinche': 'affinché', 'benche': 'benché', 'nonche': 'nonché',
            'giacche': 'giacché', 'sicche': 'sicché', 'cosicche': 'cosicché',
            'anziche': 'anziché'}
_PROTECT_APOS = {"po'", "mo'", "be'", "to'"}
_VOW_GRAVE = {'a': 'à', 'o': 'ò', 'i': 'ì', 'u': 'ù'}


def _accenta(tok):
    low = tok.lower()
    if low in _PROTECT_APOS:
        return tok
    lastv = tok[-2].lower()
    stem = tok[:-2]
    if lastv == 'e':
        rep = _ACUTE_E.get(low[:-1], stem + 'è')
    elif lastv in _VOW_GRAVE:
        rep = stem + _VOW_GRAVE[lastv]
    else:
        return tok
    return rep[0].upper() + rep[1:] if tok[0].isupper() else rep


def normalizza(text):
    if not text:
        return text
    text = re.sub(r"[A-Za-zàèéìòùÀÈÉÌÒÙ]*[aeiouAEIOU]'", lambda m: _accenta(m.group(0)), text)
    text = (text.replace(' — ', ', ').replace(' —', ',').replace('— ', ', ').replace('—', ', '))
    return re.sub(r',\s*,', ',', text)


def _claude_call(prompt, timeout=900, web=False):
    """CLI headless. web=True abilita la ricerca (scoperta + verifica)."""
    claude_bin = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~/.local/node/bin')}:{env.get('PATH', '')}"
    cmd = [claude_bin, '-p', prompt, '--output-format', 'json']
    if web:
        cmd += ['--allowedTools', 'WebSearch', 'WebFetch']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    out = r.stdout
    try:
        outer = json.loads(out)
        txt = outer.get('result', out)
    except Exception:
        txt = out
    return txt


def _estrai_json(txt, array=False):
    """Estrae il primo valore JSON completo, ignorando eventuale testo dopo
    (il modello a volte aggiunge una spiegazione in coda all'array/oggetto)."""
    open_ch = '[' if array else '{'
    i = txt.find(open_ch)
    if i < 0:
        raise ValueError('nessun JSON trovato nella risposta')
    try:
        obj, _ = json.JSONDecoder().raw_decode(txt[i:])
        return obj
    except ValueError as e:
        raise ValueError(f'JSON non interpretabile: {e}')


PROMPT_SCOPERTA = """Sei un cronista di tennis. Usa la ricerca web per trovare le notizie di tennis SIGNIFICATIVE di oggi {data} e delle ultime 48 ore, da fonti affidabili: siti ufficiali (ATP, WTA, ITF, Federtennis), grandi testate sportive, account ufficiali verificati.

Categorie che ci interessano: cambio allenatore, infortunio, forfait/ritiro da un torneo, annuncio di fine carriera, vittoria di un titolo, traguardo o record, squalifica, wild card o sorteggio di rilievo, rientro dopo uno stop.

REGOLE FERME:
- NON inventare nulla. Riporta SOLO notizie che compaiono davvero nei risultati di ricerca, con URL reali e verificabili.
- Niente rumor non confermati, niente indiscrezioni di social non ufficiali.
- Se oggi non c'e' nulla di davvero significativo, restituisci un array vuoto [].

Restituisci SOLO un array JSON (nient'altro), al massimo 6 notizie, le piu' rilevanti. Ogni elemento:
{{"headline":"titolo sintetico del fatto","summary":"1-2 frasi su cosa e' successo","category":"una fra: cambio-allenatore, infortunio, forfait, ritiro-carriera, titolo, traguardo, squalifica, wild-card, rientro, altro","entities":["giocatori o tornei coinvolti"],"sources":["url reale 1","url reale 2"],"date":"YYYY-MM-DD"}}"""

PROMPT_VERIFICA = """Sei un verificatore indipendente di notizie di tennis. Ti do una notizia candidata. Verificala sul web da fonti affidabili, in modo indipendente.

NOTIZIA CANDIDATA:
{item}

Compiti:
1. E' vera? E' confermata da almeno DUE fonti indipendenti affidabili, oppure da UNA fonte ufficiale (ATP/WTA/ITF, la federazione, il torneo, o l'interessato con comunicato ufficiale)?
2. I dettagli (nomi, numeri, date, torneo, ruoli) sono corretti? Correggi quelli sbagliati.

Sii severo: se trovi solo una fonte non ufficiale, o fonti che si copiano a vicenda, o nessuna conferma, il verdetto e' NON_CONFERMATA.

Restituisci SOLO JSON:
{{"verdict":"CONFERMATA o NON_CONFERMATA","fatto_verificato":"il fatto preciso e corretto come risulta dalle fonti, in una o due frasi","fonti_conferma":[{{"nome":"nome fonte","url":"url"}}],"data_fatto":"YYYY-MM-DD","note":"eventuali precisazioni"}}"""

PROMPT_SCRITTURA = """Sei un redattore di AnalisiTennis, testata editoriale di tennis. Scrivi una breve notizia a partire ESCLUSIVAMENTE dal fatto verificato qui sotto. Non aggiungere NESSUN dettaglio (numeri, cause, date, dichiarazioni) che non sia gia' nel fatto verificato.

FATTO VERIFICATO: {fatto}
FONTI: {fonti}
CATEGORIA: {category}

Stile: cronaca sobria e professionale, niente trattino lungo (usa la virgola), accenti corretti (è, più, città, perché), niente linguaggio da scommesse. Cita la fonte nel corpo (es. "secondo {fonte_principale}"). Non pronosticare, non speculare.

IMPORTANTE: NON aggiungere nessun dettaglio che non sia nel fatto verificato: niente nazionalità, età, palmares, cause, cifre o dichiarazioni non presenti. Riporta solo il fatto e la sua attribuzione alla fonte. Se il fatto è scarno, la notizia è scarna: va bene.

Restituisci SOLO JSON:
{{"titolo":"titolo giornalistico chiaro","sommario":"una frase di sintesi","corpo_markdown":"2-4 paragrafi brevi, con l'attribuzione alla fonte","tag":["entita' principali, 2-5 tag"]}}"""

PROMPT_GATE = """Gate anti-allucinazione per una notizia di tennis. Verifica che la notizia non affermi FATTI SOSTANZIALI non supportati.

FATTO VERIFICATO (confermato dalle fonti): {fatto}
FONTI CONFERMANTI: {fonti}

NOTIZIA SCRITTA:
titolo: {titolo}
corpo: {corpo}

Metti ok=false SOLO se la notizia afferma un fatto sostanziale, cioe' un numero, un risultato, una data, una causa, una dichiarazione o un attributo (es. nazionalita', eta', titoli), che NON e' contenuto nel fatto verificato ne' deducibile da esso.

NON segnalare come problema: l'attribuzione a una delle fonti conferma (citare la fonte e' corretto e richiesto), la riformulazione del fatto verificato, le frasi di contesto generiche che non introducono nuovi fatti.

Restituisci SOLO JSON: {{"ok":true o false,"problemi":["solo i fatti sostanziali non supportati, se ce ne sono"]}}"""


def _chiave_notizia(cat, entities, data_fatto):
    ent = _slugify('-'.join(sorted(e.lower() for e in (entities or []))[:2]))
    return f'{data_fatto}-{cat}-{ent}'


def _gia_pubblicata(chiave):
    for f in NEWS_DIR.glob('*.md'):
        m = re.search(r'^chiave:\s*"?(.*?)"?\s*$', f.read_text(), re.M)
        if m and m.group(1) == chiave:
            return True
    return False


def scopri(data_iso):
    txt = _claude_call(PROMPT_SCOPERTA.format(data=data_iso), timeout=600, web=True)
    try:
        items = _estrai_json(txt, array=True)
    except Exception as e:
        print(f'[news] scoperta: nessun JSON valido ({e})', flush=True)
        return []
    out = [i for i in items if i.get('headline') and i.get('sources')]
    print(f'[news] scoperte {len(out)} notizie candidate', flush=True)
    return out


def verifica(item):
    txt = _claude_call(PROMPT_VERIFICA.format(item=json.dumps(item, ensure_ascii=False)),
                       timeout=600, web=True)
    try:
        v = _estrai_json(txt)
    except Exception as e:
        print(f'[news]   verifica fallita (no JSON): {e}', flush=True)
        return None
    return v


def scrivi(fatto, fonti, category):
    fonte_principale = fonti[0]['nome'] if fonti else 'le fonti ufficiali'
    txt = _claude_call(PROMPT_SCRITTURA.format(
        fatto=fatto, fonti=json.dumps(fonti, ensure_ascii=False),
        category=category, fonte_principale=fonte_principale), timeout=600)
    return _estrai_json(txt)


def gate(fatto, fonti, art):
    txt = _claude_call(PROMPT_GATE.format(
        fatto=fatto, fonti=json.dumps(fonti, ensure_ascii=False),
        titolo=art.get('titolo', ''), corpo=art.get('corpo_markdown', '')), timeout=300)
    try:
        return _estrai_json(txt)
    except Exception:
        return {'ok': False, 'problemi': ['gate: risposta non interpretabile']}


def salva(art, v, item, data_iso):
    now = _now_rome()
    titolo = normalizza(art['titolo'])
    sommario = normalizza(art.get('sommario', ''))
    corpo = normalizza(art['corpo_markdown'])
    cat = item.get('category', 'altro')
    if cat not in CATEGORIE:
        cat = 'altro'
    fonti = v.get('fonti_conferma', [])
    fonte_url = fonti[0]['url'] if fonti else (item.get('sources') or [''])[0]
    fonte_nome = fonti[0]['nome'] if fonti else ''
    data_fatto = v.get('data_fatto') or item.get('date') or data_iso
    chiave = _chiave_notizia(cat, item.get('entities'), data_fatto)
    slug = f"{data_fatto}-{_slugify(titolo)}"[:90]
    tag = [normalizza(t) for t in (art.get('tag') or [])]

    fm = [
        '---',
        f'titolo: "{titolo.replace(chr(34), chr(39))}"',
        f'sommario: "{sommario.replace(chr(34), chr(39))}"',
        f'data: "{data_fatto}"',
        'autore: "Redazione AnalisiTennis"',
        f'categoria: "{cat}"',
        f'chiave: "{chiave}"',
        f'fonte_nome: "{fonte_nome.replace(chr(34), chr(39))}"',
        f'fonte_url: "{fonte_url}"',
        'tag:',
    ]
    for t in tag:
        fm.append(f'  - "{t.replace(chr(34), chr(39))}"')
    fm += [
        f'generato_il: "{now.strftime("%Y-%m-%dT%H:%M")}"',
        'pubblicato: true',
        '---',
        '',
        corpo,
    ]
    dest = NEWS_DIR / f'{slug}.md'
    dest.write_text('\n'.join(fm))
    return dest


def run(data_iso):
    if os.environ.get('ANALISITENNIS_NEWS', '1') == '0':
        print('[news] disattivata (ANALISITENNIS_NEWS=0)')
        return
    candidate = scopri(data_iso)
    pubblicate = 0
    scartate = []
    for item in candidate:
        hd = item.get('headline', '?')
        print(f'[news] verifico: {hd[:70]}', flush=True)
        chiave_prelim = _chiave_notizia(item.get('category', 'altro'),
                                        item.get('entities'), item.get('date') or data_iso)
        if _gia_pubblicata(chiave_prelim):
            print('[news]   gia pubblicata, skip', flush=True)
            continue
        v = verifica(item)
        if not v or v.get('verdict') != 'CONFERMATA':
            print(f'[news]   NON confermata, scarto', flush=True)
            scartate.append({'headline': hd, 'motivo': (v or {}).get('note', 'non confermata')})
            continue
        fatto = v.get('fatto_verificato', '')
        fonti = v.get('fonti_conferma', [])
        if not fatto or not fonti:
            print('[news]   confermata ma senza fatto/fonti, scarto', flush=True)
            continue
        try:
            art = scrivi(fatto, fonti, item.get('category', 'altro'))
        except Exception as e:
            print(f'[news]   scrittura fallita: {e}', flush=True)
            continue
        g = gate(fatto, fonti, art)
        if not g.get('ok'):
            print(f'[news]   gate FALLITO: {g.get("problemi")}', flush=True)
            scartate.append({'headline': hd, 'motivo': 'gate: ' + '; '.join(g.get('problemi', []))})
            continue
        dest = salva(art, v, item, data_iso)
        pubblicate += 1
        print(f'[news]   PUBBLICATA -> {dest.name}', flush=True)
    print(f'[news] fatto: {pubblicate} pubblicate, {len(scartate)} scartate', flush=True)
    if scartate:
        (ROOT / 'backend' / f'news_scartate_{data_iso}.json').write_text(
            json.dumps(scartate, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    run(d)
