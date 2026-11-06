"""Genera profili editoriali per giocatori e tornei usando claude CLI headless.

Un profilo si crea una tantum per entita'. Idempotente: se gia' esiste il file
in src/content/giocatori-profilo/ o src/content/tornei-profilo/ non viene
rigenerato.

Uso:
    python3 generate_profiles.py player "L. Sonego"
    python3 generate_profiles.py tournament "Vienna" 2026
    python3 generate_profiles.py backfill  # genera profili per tutti i giocatori/tornei degli articoli esistenti
"""
from __future__ import annotations
import json
import os
import re
import sys
import shutil
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    def _now_rome():
        return datetime.now(ZoneInfo('Europe/Rome'))
except Exception:
    def _now_rome():
        return datetime.now()

ROOT = Path(__file__).resolve().parent.parent
PROFILI_GIOCATORI = ROOT / 'src' / 'content' / 'giocatori-profilo'
PROFILI_TORNEI = ROOT / 'src' / 'content' / 'tornei-profilo'
PROFILI_GIOCATORI.mkdir(parents=True, exist_ok=True)
PROFILI_TORNEI.mkdir(parents=True, exist_ok=True)


# --- Identita' robusta: un giocatore = un profilo ---
# Il sito identifica i giocatori con lo slug derivato dal nome abbreviato
# dell'API ("J. Fonseca" -> j-fonseca), mentre la copertura classifica parte
# dal nome completo ("Joao Fonseca" -> joao-fonseca). Senza un confronto per
# persona si creerebbero profili duplicati. Qui si riconosce lo stesso
# giocatore anche fra forma abbreviata ed estesa, con ordine nomi diverso e
# cognomi multipli.
def _nome_norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s or ''))
                   if not unicodedata.combining(c)).lower()


def _nome_token(s):
    return [t for t in re.split(r'[^a-z]+', _nome_norm(s)) if len(t) > 1]


def _stessa_persona(a, b):
    """True se a e b indicano lo stesso giocatore. Con entrambi i nomi estesi
    (>=2 token) usa il sottoinsieme di token (tollera ordine e cognomi
    multipli). Con un lato abbreviato (un solo cognome) richiede cognome in
    comune e iniziale del nome presente fra le iniziali dell'altro."""
    ta, tb = set(_nome_token(a)), set(_nome_token(b))
    if not ta or not tb:
        return False
    shared = ta & tb
    if not shared:
        return False
    if len(ta) >= 2 and len(tb) >= 2:
        small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        return small <= big and len(small & big) >= 2
    # un lato abbreviato: confronta l'iniziale del nome
    def iniziale(x):
        n = _nome_norm(x).strip()
        return n[0] if n else ''
    abbr, full = (a, b) if len(ta) <= len(tb) else (b, a)
    full_iniziali = {t[0] for t in _nome_token(full)}
    return iniziale(abbr) in full_iniziali


def _profili_esistenti():
    out = []
    for f in PROFILI_GIOCATORI.glob('*.md'):
        m = re.search(r'^nome:\s*"?(.*?)"?\s*$', f.read_text(), re.M)
        if m:
            out.append((f.stem, m.group(1)))
    return out


def _slug_profilo_persona(nome):
    """Slug del profilo esistente che rappresenta questa persona, o None."""
    for slug, prof_nome in _profili_esistenti():
        if _stessa_persona(nome, prof_nome):
            return slug
    return None

# Mappa nomi abbreviati -> nome completo. Sincronizzata con attach_covers.NAME_MAP.
try:
    from attach_covers import NAME_MAP
except Exception:
    NAME_MAP = {}


def slugify(s: str) -> str:
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s)[:80]


def display_player_name(raw: str) -> str:
    return NAME_MAP.get(raw, raw)


def tournament_display(raw: str) -> str:
    return re.sub(r"\s*-\s*Qualification$", "", raw or "").strip()


def tournament_slug(raw: str, year: int) -> str:
    return f"{slugify(tournament_display(raw))}-{year}"


def player_slug(raw: str) -> str:
    return slugify(display_player_name(raw))


# ---------- claude CLI ----------

def _claude_call(prompt: str, timeout: int = 900, web: bool = False) -> dict:
    """Chiama la CLI headless di Claude e restituisce il primo oggetto JSON.

    web=True abilita la ricerca sul web (WebSearch + WebFetch) per lo stadio di
    documentazione: senza questo flag la CLI headless non ha alcun accesso alla
    rete e il modello scrive solo dalla sua memoria, che e' vecchia e produce i
    dossier magri all'origine dei profili respinti dal gate. Scrittura e gate
    NON usano il web: restano ancorati al dossier verificato.
    """
    claude_bin = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~/.local/node/bin')}:{env.get('PATH','')}"
    cmd = [claude_bin, '-p', prompt, '--output-format', 'json']
    if web:
        # In modalita' headless i tool elencati qui sono auto-approvati; tutto il
        # resto resta negato, quindi la ricerca non puo' toccare il filesystem.
        # L'agente cicla da solo (cerca -> apri -> verifica) fino alla risposta.
        cmd += ['--allowedTools', 'WebSearch', 'WebFetch']
    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=timeout, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f'claude CLI fallita: {result.stderr[:500]}')
    try:
        wrapper = json.loads(result.stdout)
        content = wrapper.get('result') or wrapper.get('content') or result.stdout
    except json.JSONDecodeError:
        content = result.stdout
    start = content.find('{')
    end = content.rfind('}') + 1
    if start < 0 or end <= start:
        raise RuntimeError(f'JSON non trovato: {content[:300]}')
    return json.loads(content[start:end])


# ---------- PROMPT ----------

# Stadio 1: RICERCA. Prima si verifica, poi si scrive.
# Fino al novembre 2026 questo stadio non esisteva: il profilo veniva scritto
# direttamente dalla memoria del modello, e il campo `mano` era perfino chiesto
# come scelta binaria obbligata "destro|mancino". Su un giocatore poco noto era
# una tirata a indovinare, ed e' cosi' che Weronika Falkowska, destra, e' stata
# pubblicata come mancina in ogni riga della sua scheda finche' un lettore non
# l'ha segnalato via email alla redazione.
PROMPT_RICERCA_GIOCATORE = """Sei il documentalista della testata AnalisiTennis.
NON devi scrivere un articolo. Devi VERIFICARE sul web chi e' il tennista "{nome}"
e restituire solo i dati che hai davvero riscontrato.

Il nome che ti diamo arriva da un tabellone e puo' essere abbreviato o storpiato
(es. "W. Falkowska", "H. Shi", "J. Paul"). Il tuo primo compito e' capire di chi
si tratta davvero, incrociando nazionalita', data di nascita e risultati recenti.
Attenzione agli omonimi e ai casi padre/figlio.

FONTI AMMESSE, in ordine di priorita':
1. atptour.com, wtatennis.com, itftennis.com (le schede giocatore riportano
   "Plays: Right/Left Handed", nazionalita' e data di nascita)
2. Wikipedia, preferibilmente in inglese (campo "Plays")
3. tennisabstract.com, Sofascore, Flashscore come conferma incrociata
Per la MANO servono almeno due fonti concordi oppure una scheda ufficiale di
circuito. Stessa soglia per il rovescio.

REGOLA ASSOLUTA: se un dato non lo verifichi, il valore e' null. Mai indovinare,
mai dedurre dal nome, dalla nazionalita' o dal tipo di gioco. Un campo vuoto non
fa alcun danno, un campo sbagliato e' un errore pubblicato che i lettori vedono.

Restituisci SOLO questo JSON, nulla prima e nulla dopo:

```json
{{
  "identificato": true/false,
  "nome": "nome completo come compare nel circuito, oppure null",
  "sesso": "m|f|null (serve per non descrivere una giocatrice al maschile)",
  "nazionalita": "in italiano, oppure null",
  "data_nascita": "YYYY-MM-DD oppure null",
  "altezza": "es. 189 cm, oppure null",
  "mano": "destro|mancino|null",
  "rovescio": "una mano|due mani|null",
  "categoria": "ATP|WTA|Challenger|ITF|null",
  "fonti": ["URL effettivamente consultati, uno per dato chiave"],
  "fatti_verificati": [
    "elenco di fatti accertati con la fonte accanto: titoli con nome e anno,
     best ranking con la data, risultati Slam, medaglie, infortuni rilevanti,
     cambi di bandiera. Solo cio' che hai riscontrato."
  ],
  "non_verificati": ["dati che hai cercato e NON sei riuscito a confermare"]
}}
```

Se dopo la ricerca non riesci a stabilire con certezza di chi si tratti, metti
"identificato": false e lascia null tutto il resto: la redazione non pubblica
schede su persone che non sa identificare.
"""


PROMPT_GIOCATORE = """Sei un giornalista sportivo italiano, redattore della testata editoriale
AnalisiTennis. Devi scrivere un PROFILO EDITORIALE del tennista {nome}.

DOSSIER VERIFICATO (fonte unica della verita'):
{dossier}

REGOLA SUGLI ATTRIBUTI: mano, rovescio, nazionalita', data di nascita, altezza e
categoria si scrivono SOLO se compaiono nel dossier qui sopra con un valore.
Dove il dossier dice null, il campo va OMESSO dal JSON e l'attributo non va
nominato nel testo in nessuna forma, nemmeno allusiva ("le traiettorie del
mancino", "il piu' giovane dei due"). Non dedurre il sesso dal circuito: usalo
dal campo "sesso" del dossier, e se e' null scrivi in modo neutro.

REGOLE NON NEGOZIABILI:
1. PROSA fluida in italiano, nessun elenco puntato nel corpo tranne nelle sezioni
   "Trofei principali" dove un elenco markdown e' consentito.
2. Lunghezza 450-700 parole totali.
3. Tono: redazionale, autorevole, mai da scommesse, mai da bookmaker.
4. ANTI-ALLUCINAZIONE: i fatti specifici (titoli, anni, ranking, risultati
   Slam, medaglie) si prendono dal dossier verificato. Quello che nel dossier
   non c'e', non si scrive: usa formulazioni generiche ("alcuni titoli
   Challenger", "nelle prime stagioni sul tour maggiore") senza INVENTARE
   date, score o eventi. MEGLIO una frase piu' prudente che un fatto sbagliato.
   Non fidarti della tua memoria nemmeno sui giocatori famosi: i numeri di
   titoli e i best ranking cambiano ogni settimana e la tua e' vecchia.
4-bis. NIENTE CONTENUTO DEPERIBILE: il profilo deve restare vero anche fra sei
   mesi. Vietati i bilanci stagionali ("nove vittorie e sei sconfitte"), i
   riferimenti a partite imminenti e le formule tipo "in questi giorni" o
   "arriva da favorito". Le classifiche vanno sempre ancorate a una data
   esplicita ("numero 5 del mondo nel luglio 2026"), mai date al presente.
5. Niente riferimenti a bookmaker, quote, scommesse, stake, EV, pick.
6. Niente abbreviazioni oscure (sempre "scontri diretti" non "H2H", "palle
   break" non "BP").
7. Niente ovvieta' da enciclopedia ("il tennis e' uno sport in cui..."),
   vai dritto al punto che riguarda lui.
8. Mini-titoli markdown H2 (## Titoletto) obbligatori per queste sezioni:
     - ## Chi è
     - ## Il suo tennis
     - ## Sulle diverse superfici
     - ## Trofei e momenti chiave
   Niente altri H1. Puoi usare H3 come sotto-divisioni dentro le sezioni.

**OUTPUT RICHIESTO** (JSON, nulla prima o dopo):

```json
{{
  "nome": "nome completo del giocatore come appare nel circuito",
  "nazionalita": "Italia (o altra, in italiano)",
  "data_nascita": "copiala dal dossier; se li' e' null, OMETTI il campo",
  "mano": "copiala dal dossier; se li' e' null, OMETTI il campo (mai indovinare)",
  "rovescio": "copialo dal dossier; se li' e' null, OMETTI il campo",
  "stile_gioco": "breve descrizione tecnica dello stile, 4-9 parole (es. 'servizio potente e dritto d'attacco', 'difesa e varieta' da fondo'). NON il solo rovescio.",
  "titoli": "sintesi onesta dei titoli/traguardi (es. '24 Slam, oltre 90 titoli ATP', 'un titolo ATP sulla terra', 'alcuni titoli Challenger'). Se non sei certo di numeri, resta qualitativo. Ometti del tutto il campo se non hai nulla di affidabile.",
  "altezza": "es. 189 cm (se noto)",
  "categoria": "ATP|WTA|Challenger|Slam",
  "superficie_preferita": "cemento|terra|erba|indoor (quella in cui storicamente va meglio)",
  "intro": "una frase, 160-220 caratteri, che apre il profilo nella hero (senza anticipazioni di gossip, niente predizioni)",
  "descrizione": "meta description SEO 150-160 caratteri",
  "corpo_markdown": "ARTICOLO completo con i mini-titoli H2 obbligatori, 450-700 parole",
  "tag": ["5-8 keyword SEO: nome, cognome, nazionalita', categoria, superficie forte"]
}}
```
"""


PROMPT_RICERCA_TORNEO = """Sei il documentalista della testata AnalisiTennis.
NON devi scrivere un articolo. Devi VERIFICARE sul web quale torneo di tennis sia
"{nome}" nell'edizione {anno} e restituire solo i dati riscontrati.

ATTENZIONE, errore tipico da evitare: il nome di una citta' NON identifica un
torneo. In molte sedi convivono un evento maschile e uno femminile, con nomi
ufficiali, storie e albi d'oro completamente separati, e in diverse citta' un
torneo storico e' stato dismesso o trasferito e sostituito da un altro. Il nome
grezzo che ti diamo arriva da un tabellone e puo' contenere rumore come
"- Qualification" o il paese fra parentesi. Il nome originale e': "{raw}".

Stabilisci con certezza DI QUALE evento si tratta nel {anno}: circuito (ATP,
WTA, Challenger, ITF), livello esatto, sede, superficie reale e se si gioca al
coperto. Verifica anche se il torneo abbia cambiato citta', nome o periodo.

FONTI AMMESSE: atptour.com, wtatennis.com, itftennis.com, il sito ufficiale del
torneo, Wikipedia (pagina del torneo e pagina dell'edizione specifica).
Per l'albo d'oro incrocia la pagina del torneo con quella delle singole edizioni.

REGOLA ASSOLUTA: se un dato non lo verifichi, il valore e' null e l'albo d'oro
resta vuoto. Mai dedurre un vincitore dalla fama del giocatore.

Restituisci SOLO questo JSON, nulla prima e nulla dopo:

```json
{{
  "identificato": true/false,
  "nome": "nome ufficiale corrente dell'evento, oppure null",
  "citta": "oppure null", "paese": "in italiano, oppure null",
  "categoria": "ATP|WTA|Challenger|Slam|Masters|null",
  "superficie": "cemento|terra|erba|null (il materiale, non la condizione)",
  "al_coperto": true/false/null,
  "impianto": "nome dell'impianto, oppure null",
  "fondato": "anno della prima edizione, oppure null",
  "fonti": ["URL effettivamente consultati"],
  "albo_oro": ["una riga per edizione verificata: anno, vincitore, finalista"],
  "note_storiche": ["trasferimenti di sede, cambi di nome, interruzioni, e
                     l'eventuale esistenza di un altro torneo nella stessa
                     citta' da non confondere con questo"],
  "non_verificati": ["dati che hai cercato e non hai confermato"]
}}
```
"""


PROMPT_TORNEO = """Sei un giornalista sportivo italiano, redattore della testata editoriale
AnalisiTennis. Devi scrivere un PROFILO EDITORIALE del torneo {nome} {anno}.

DOSSIER VERIFICATO (fonte unica della verita'):
{dossier}

REGOLA SUI DATI: nome ufficiale, citta', paese, categoria, superficie, anno di
fondazione e albo d'oro si prendono SOLO dal dossier. Un vincitore che non e'
nell'albo d'oro del dossier non si cita, nemmeno se ti sembra ovvio. Nel campo
`superficie` scrivi il materiale (cemento, terra, erba): se si gioca al coperto
dillo nel testo, perche' "indoor" e' una condizione, non una superficie.

REGOLE NON NEGOZIABILI:
1. PROSA fluida in italiano, nessun elenco puntato nel corpo tranne nelle sezioni
   "Albo d'oro recente" dove un elenco markdown breve e' consentito.
2. Lunghezza 450-700 parole.
3. Tono redazionale, autorevole, mai da scommesse.
4. ANTI-ALLUCINAZIONE: cita solo fatti NOTORI del torneo (nome ufficiale,
   impianto, superficie, categoria, decade di fondazione). Se non ricordi con
   certezza l'anno esatto, usa formulazioni generiche ("negli anni Settanta",
   "a cavallo degli anni 2000"). Meglio prudente che inesatto.
5. Mini-titoli H2 obbligatori:
     - ## La storia
     - ## Il campo e lo stile
     - ## Albo d'oro recente
     - ## Curiosità
6. Niente riferimenti a bookmaker, scommesse, quote.
7. Niente H1 nel corpo.

**OUTPUT RICHIESTO** (JSON, nulla prima o dopo):

```json
{{
  "nome": "nome ufficiale del torneo",
  "anno": {anno},
  "citta": "citta' sede",
  "paese": "nazione in italiano",
  "categoria": "ATP|WTA|Challenger|Slam|Masters",
  "superficie": "cemento|terra|erba|indoor",
  "fondato": "anno approssimativo di fondazione o 'anni X0' se incerto",
  "intro": "frase 160-220 caratteri per la hero",
  "descrizione": "meta description SEO 150-160 caratteri",
  "corpo_markdown": "ARTICOLO 450-700 parole con mini-titoli H2 obbligatori",
  "tag": ["5-8 keyword SEO"]
}}
```
"""


# ---------- WRITER ----------

def _yaml_quote(v: str) -> str:
    return str(v).replace('"', "'")


def _write_frontmatter(path: Path, fm: dict, body: str):
    lines = ['---']
    for k, v in fm.items():
        if v is None or v == '':
            continue
        if isinstance(v, list):
            lines.append(f'{k}:')
            for item in v:
                lines.append(f'  - "{_yaml_quote(item)}"')
        elif isinstance(v, bool):
            lines.append(f'{k}: {str(v).lower()}')
        elif isinstance(v, int):
            lines.append(f'{k}: {v}')
        else:
            lines.append(f'{k}: "{_yaml_quote(v)}"')
    lines.append('---')
    lines.append('')
    lines.append(body)
    path.write_text('\n'.join(lines))


PROMPT_GATE_PROFILO = """Sei il revisore dei fatti di AnalisiTennis. Controlli un profilo
PRIMA della pubblicazione. Sii severo: quello che passa di qui finisce online.

DOSSIER VERIFICATO (fonte unica della verita'):
{dossier}

PROFILO DA CONTROLLARE:
{profilo}

Cerca questi errori, in quest'ordine di gravita':
1. ATTRIBUTI NON VERIFICATI O CONTRADDETTI. Mano, rovescio, nazionalita', data
   di nascita, altezza, categoria: se il profilo li afferma e il dossier dice
   altro, o dice null, e' un errore grave. Vale anche per le allusioni
   indirette ("le traiettorie del mancino", "il braccio sinistro").
   Questo e' il controllo piu' importante: un errore di questo tipo e' gia'
   stato segnalato alla redazione da un lettore.
2. SESSO SBAGLIATO. Se il dossier dice "f" e il testo usa il maschile (o
   viceversa), e' un errore grave: va corretto in tutta la prosa.
3. FATTI NON NEL DOSSIER. Titoli, anni, ranking, risultati Slam, medaglie,
   convocazioni in nazionale: se non sono nel dossier, non si pubblicano.
4. CONTENUTO DEPERIBILE. Bilanci stagionali, anteprime di partite, classifiche
   date al presente senza una data: invecchiano male e diventano falsi da soli.
5. STILE. Trattino lungo (vietato), apostrofo ASCII al posto delle lettere
   accentate ("e'" invece di "e"), lessico da scommesse o pronostici.

Restituisci SOLO questo JSON:

```json
{{
  "verdict": "PASS|FAIL",
  "errori": ["elenco preciso: la frase incriminata e perche' e' sbagliata"],
  "correzioni_suggerite": ["per ogni errore, come andrebbe scritto"]
}}
```
"""


def _ricerca_giocatore(nome_display: str) -> dict:
    """Stadio 1: verifica sul web chi e' il giocatore e cosa e' documentato.

    Se la ricerca fallisce, ripieghiamo sugli attributi gia' verificati in
    archivio (fact_store): meglio pochi dati certi che molti inventati.
    """
    try:
        dossier = _claude_call(PROMPT_RICERCA_GIOCATORE.format(nome=nome_display),
                               timeout=1200, web=True)
        if dossier.get('identificato'):
            return dossier
        print(f'[player] NON identificato dalla ricerca: {nome_display}')
        return dossier
    except Exception as e:
        print(f'[player] ricerca fallita ({e}), ripiego sull\'archivio verificato')
    try:
        from fact_store import fatti_giocatore
        d = fatti_giocatore(nome_display) or {}
        return {
            'identificato': bool(d),
            'nome': d.get('nome') or nome_display,
            'sesso': None,
            'nazionalita': d.get('nazionalita'),
            'data_nascita': d.get('data_nascita'),
            'altezza': d.get('altezza'),
            'mano': d.get('mano'),
            'rovescio': d.get('rovescio'),
            'categoria': d.get('categoria'),
            'fonti': [], 'fatti_verificati': [], 'non_verificati': [],
        }
    except Exception:
        return {'identificato': False}


def _ricerca_torneo(nome_display: str, anno: int, raw_name: str = '') -> dict:
    """Stadio 1 per i tornei: stabilisce DI QUALE evento stiamo parlando."""
    try:
        dossier = _claude_call(PROMPT_RICERCA_TORNEO.format(
            nome=nome_display, anno=anno, raw=raw_name or nome_display),
            timeout=1200, web=True)
        if not dossier.get('identificato'):
            print(f'[tournament] NON identificato dalla ricerca: {nome_display} {anno}')
        return dossier
    except Exception as e:
        print(f'[tournament] ricerca fallita ({e}), ripiego sull\'archivio verificato')
    try:
        from fact_store import fatti_torneo
        d = fatti_torneo(nome_display, anno) or {}
        return {
            'identificato': bool(d),
            'nome': d.get('nome'), 'citta': d.get('citta'), 'paese': d.get('paese'),
            'categoria': d.get('categoria'), 'superficie': d.get('superficie'),
            'al_coperto': None, 'impianto': None, 'fondato': d.get('fondato'),
            'fonti': [], 'albo_oro': [], 'note_storiche': [], 'non_verificati': [],
        }
    except Exception:
        return {'identificato': False}


def generate_player_profile(raw_name: str, overwrite: bool = False) -> Path | None:
    nome_display = display_player_name(raw_name)
    if nome_display in ('Redazione', 'Lettori'):
        return None
    slug = player_slug(raw_name)
    if not slug or len(slug) < 2:
        print(f'[player] skip slug invalido: {raw_name}')
        return None
    dest = PROFILI_GIOCATORI / f'{slug}.md'
    if dest.exists() and not overwrite:
        print(f'[player] gia esistente: {slug}')
        return dest
    # Dedup per persona: evita un secondo profilo quando lo stesso giocatore
    # esiste gia' con uno slug diverso (es. coperto come "Joao Fonseca" ->
    # joao-fonseca, poi incontrato in un match come "J. Fonseca" -> j-fonseca).
    if not overwrite:
        esistente = _slug_profilo_persona(nome_display)
        if esistente and esistente != slug:
            print(f'[player] stessa persona gia a profilo ({esistente}), skip {slug}')
            return PROFILI_GIOCATORI / f'{esistente}.md'
    print(f'[player] genero profilo: {nome_display} ({slug})')

    # Stadio 1: ricerca e verifica. Senza identificazione non si pubblica.
    dossier = _ricerca_giocatore(nome_display)
    if not dossier.get('identificato'):
        print(f'[player] SALTATO {slug}: giocatore non identificato con certezza. '
              f'Meglio nessuna scheda che una scheda inventata.')
        return None
    dossier_txt = json.dumps(dossier, ensure_ascii=False, indent=2)

    # Stadio 2: scrittura, ancorata al dossier.
    try:
        data = _claude_call(PROMPT_GIOCATORE.format(nome=nome_display, dossier=dossier_txt))
    except Exception as e:
        print(f'[player] errore claude: {e}')
        return None

    # Stadio 3: gate di fact-check. Un solo tentativo di rigenerazione, poi
    # si rinuncia: pubblicare un profilo che non passa il controllo sarebbe
    # esattamente l'errore che questo gate esiste per impedire.
    for tentativo in (1, 2):
        try:
            esito = _claude_call(PROMPT_GATE_PROFILO.format(
                dossier=dossier_txt,
                profilo=json.dumps(data, ensure_ascii=False, indent=2)[:12000],
            ))
        except Exception as e:
            print(f'[player] gate non eseguito ({e}): pubblico con riserva')
            break
        if esito.get('verdict') == 'PASS':
            print(f'[player] gate superato ({slug})')
            break
        errori = esito.get('errori') or []
        print(f'[player] gate FALLITO ({slug}), tentativo {tentativo}: {errori[:3]}')
        if tentativo == 2:
            print(f'[player] SALTATO {slug}: il profilo non supera il fact-check.')
            return None
        try:
            data = _claude_call(
                PROMPT_GIOCATORE.format(nome=nome_display, dossier=dossier_txt)
                + '\n\nIl tentativo precedente e\' stato respinto dal revisore per questi '
                  'errori, da non ripetere:\n' + json.dumps(errori, ensure_ascii=False)
            )
        except Exception as e:
            print(f'[player] rigenerazione fallita: {e}')
            return None

    fm = {
        'nome': data.get('nome') or nome_display,
        'slug_profilo': slug,
        'nazionalita': data.get('nazionalita'),
        'data_nascita': data.get('data_nascita'),
        'mano': data.get('mano'),
        'rovescio': data.get('rovescio'),
        'stile_gioco': data.get('stile_gioco'),
        'titoli': data.get('titoli'),
        'altezza': data.get('altezza'),
        'categoria': data.get('categoria'),
        'superficie_preferita': data.get('superficie_preferita'),
        'intro': data.get('intro'),
        'descrizione': data.get('descrizione'),
        'tag': data.get('tag') or [],
        'pubblicato': True,
        'generato_il': _now_rome().strftime('%Y-%m-%dT%H:%M'),
    }
    _write_frontmatter(dest, fm, data.get('corpo_markdown') or '')
    print(f'[player] scritto {dest.name}')
    return dest


def generate_tournament_profile(raw_name: str, year: int, overwrite: bool = False) -> Path | None:
    nome_display = tournament_display(raw_name)
    if not nome_display or nome_display == 'Editoriale':
        return None
    slug = tournament_slug(raw_name, year)
    dest = PROFILI_TORNEI / f'{slug}.md'
    if dest.exists() and not overwrite:
        print(f'[tournament] gia esistente: {slug}')
        return dest
    print(f'[tournament] genero profilo: {nome_display} {year} ({slug})')

    # Stadio 1: ricerca. Il nome di una citta' NON identifica un torneo: in
    # molte sedi convivono un evento maschile e uno femminile, con storie e
    # albi d'oro separati. Senza questo passaggio il sito ha pubblicato per
    # giorni l'albo d'oro maschile dell'ATP di Chennai sotto le partite del
    # WTA di Chennai, e ha attribuito ad Almaty un titolo di Djokovic che era
    # di Astana.
    dossier = _ricerca_torneo(nome_display, year, raw_name)
    if not dossier.get('identificato'):
        print(f'[tournament] SALTATO {slug}: torneo non identificato con certezza.')
        return None
    dossier_txt = json.dumps(dossier, ensure_ascii=False, indent=2)

    # Stadio 2 e 3: scrittura ancorata al dossier, poi gate di fact-check.
    try:
        data = _claude_call(PROMPT_TORNEO.format(nome=nome_display, anno=year, dossier=dossier_txt))
    except Exception as e:
        print(f'[tournament] errore claude: {e}')
        return None
    for tentativo in (1, 2):
        try:
            esito = _claude_call(PROMPT_GATE_PROFILO.format(
                dossier=dossier_txt,
                profilo=json.dumps(data, ensure_ascii=False, indent=2)[:12000],
            ))
        except Exception as e:
            print(f'[tournament] gate non eseguito ({e}): pubblico con riserva')
            break
        if esito.get('verdict') == 'PASS':
            print(f'[tournament] gate superato ({slug})')
            break
        errori = esito.get('errori') or []
        print(f'[tournament] gate FALLITO ({slug}), tentativo {tentativo}: {errori[:3]}')
        if tentativo == 2:
            print(f'[tournament] SALTATO {slug}: non supera il fact-check.')
            return None
        try:
            data = _claude_call(
                PROMPT_TORNEO.format(nome=nome_display, anno=year, dossier=dossier_txt)
                + '\n\nIl tentativo precedente e\' stato respinto per questi errori, '
                  'da non ripetere:\n' + json.dumps(errori, ensure_ascii=False)
            )
        except Exception as e:
            print(f'[tournament] rigenerazione fallita: {e}')
            return None
    fm = {
        'nome': data.get('nome') or nome_display,
        'slug_profilo': slug,
        'anno': year,
        'citta': data.get('citta'),
        'paese': data.get('paese'),
        'categoria': data.get('categoria'),
        'superficie': data.get('superficie'),
        'fondato': data.get('fondato'),
        'intro': data.get('intro'),
        'descrizione': data.get('descrizione'),
        'tag': data.get('tag') or [],
        'pubblicato': True,
        'generato_il': _now_rome().strftime('%Y-%m-%dT%H:%M'),
    }
    # Cover: foto impianto/campo del torneo, mostrata nell'elenco /tornei.
    # "Aggiornato di volta in volta": ogni nuovo torneo trattato riceve
    # subito la sua cover (resize web dentro download()).
    rel, credit = _tournament_cover(raw_name, fm['nome'], slug)
    if rel:
        fm['cover_image'] = rel
        fm['cover_credit'] = credit
    _write_frontmatter(dest, fm, data.get('corpo_markdown') or '')
    print(f'[tournament] scritto {dest.name}')
    return dest


def _tournament_cover(raw_name: str, nome: str, slug: str):
    """Scarica una cover venue per il torneo in public/covers/tornei/<slug>.jpg.
    Ritorna (rel_path, credit) o (None, None) se non trova nulla."""
    try:
        from attach_covers import pick_venue, download, strip_html
        tdir = ROOT / 'public' / 'covers' / 'tornei'
        tdir.mkdir(parents=True, exist_ok=True)
        pick = None
        for key in (raw_name, nome):
            if not key:
                continue
            pick = pick_venue(key, slug_hint='torneo-' + slug)
            if pick:
                break
        if not pick:
            return None, None
        dest = tdir / f'{slug}.jpg'
        download(pick['url'], dest)
        credit = (f"{pick['title'].replace('File:', '')} | "
                  f"{strip_html(pick.get('author') or 'Autore sconosciuto')} | "
                  f"{pick.get('license') or 'Wikimedia Commons'}")
        # Virgolette doppie nei titoli Commons romperebbero lo YAML.
        credit = credit.replace('"', "'")
        return f'/covers/tornei/{slug}.jpg', credit
    except Exception as e:
        print(f'[tournament] cover errore: {e}')
        return None, None


def ensure_profiles_for_match(p1: str, p2: str, torneo: str, data: str):
    """Entry point chiamato da write_article.py dopo ogni articolo."""
    year = int((data or '')[:4]) if data and data[:4].isdigit() else _now_rome().year
    try:
        generate_player_profile(p1)
    except Exception as e:
        print(f'[player p1] errore: {e}')
    try:
        generate_player_profile(p2)
    except Exception as e:
        print(f'[player p2] errore: {e}')
    try:
        generate_tournament_profile(torneo, year)
    except Exception as e:
        print(f'[tournament] errore: {e}')


def backfill_from_articles():
    """Scorre tutti gli articoli e genera profili per giocatori/tornei mancanti."""
    articoli_dir = ROOT / 'src' / 'content' / 'articoli'
    players = set()
    tournaments = set()  # (nome, anno)
    for f in sorted(articoli_dir.glob('*.md')):
        raw = f.read_text()
        m = re.match(r"^---\n(.*?)\n---", raw, re.S)
        if not m:
            continue
        fm = m.group(1)
        def pick(k):
            mm = re.search(rf'^{k}: "?(.*?)"?$', fm, re.M)
            return mm.group(1) if mm else None
        g1, g2 = pick('giocatore1'), pick('giocatore2')
        tor = pick('torneo')
        data = pick('data')
        year = int((data or '')[:4]) if data and data[:4].isdigit() else _now_rome().year
        if g1 and g1 not in ('Redazione',):
            players.add(g1)
        if g2 and g2 not in ('Lettori',):
            players.add(g2)
        if tor and tor != 'Editoriale':
            tournaments.add((tor, year))
    print(f'backfill: {len(players)} giocatori, {len(tournaments)} tornei')
    for p in sorted(players):
        generate_player_profile(p)
    for (tor, yr) in sorted(tournaments):
        generate_tournament_profile(tor, yr)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Uso: generate_profiles.py player NAME | tournament NAME YEAR | backfill', file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'player' and len(sys.argv) >= 3:
        generate_player_profile(sys.argv[2])
    elif cmd == 'tournament' and len(sys.argv) >= 4:
        generate_tournament_profile(sys.argv[2], int(sys.argv[3]))
    elif cmd == 'backfill':
        backfill_from_articles()
    else:
        print('Comando non valido', file=sys.stderr)
        sys.exit(1)
