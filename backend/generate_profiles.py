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

def _claude_call(prompt: str, timeout: int = 900) -> dict:
    claude_bin = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')
    env = os.environ.copy()
    env['PATH'] = f"{os.path.expanduser('~/.local/node/bin')}:{env.get('PATH','')}"
    result = subprocess.run(
        [claude_bin, '-p', prompt, '--output-format', 'json'],
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

PROMPT_GIOCATORE = """Sei un giornalista sportivo italiano, redattore della testata editoriale
AnalisiTennis. Devi scrivere un PROFILO EDITORIALE del tennista {nome}.

REGOLE NON NEGOZIABILI:
1. PROSA fluida in italiano, nessun elenco puntato nel corpo tranne nelle sezioni
   "Trofei principali" dove un elenco markdown e' consentito.
2. Lunghezza 450-700 parole totali.
3. Tono: redazionale, autorevole, mai da scommesse, mai da bookmaker.
4. ANTI-ALLUCINAZIONE: cita solo fatti NOTORI e consolidati del giocatore.
   Se non ricordi con certezza un dato specifico (un titolo preciso, un anno
   esatto), usa formulazioni generiche ("alcuni titoli Challenger", "nelle
   prime stagioni sul tour maggiore") senza INVENTARE date, score o eventi
   non noti. MEGLIO una frase piu' prudente che un fatto sbagliato.
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
  "data_nascita": "YYYY-MM-DD se nota con certezza, altrimenti omettila",
  "mano": "destro|mancino",
  "rovescio": "una mano|due mani (se noto)",
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


PROMPT_TORNEO = """Sei un giornalista sportivo italiano, redattore della testata editoriale
AnalisiTennis. Devi scrivere un PROFILO EDITORIALE del torneo {nome} {anno}.

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
    print(f'[player] genero profilo: {nome_display} ({slug})')
    try:
        data = _claude_call(PROMPT_GIOCATORE.format(nome=nome_display))
    except Exception as e:
        print(f'[player] errore claude: {e}')
        return None
    fm = {
        'nome': data.get('nome') or nome_display,
        'slug_profilo': slug,
        'nazionalita': data.get('nazionalita'),
        'data_nascita': data.get('data_nascita'),
        'mano': data.get('mano'),
        'rovescio': data.get('rovescio'),
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
    try:
        data = _claude_call(PROMPT_TORNEO.format(nome=nome_display, anno=year))
    except Exception as e:
        print(f'[tournament] errore claude: {e}')
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
    _write_frontmatter(dest, fm, data.get('corpo_markdown') or '')
    print(f'[tournament] scritto {dest.name}')
    return dest


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
