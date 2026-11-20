#!/usr/bin/env python3
"""Sanity check pre-deploy per la pipeline streaming (Fase A e Fase B).

Filosofia: ogni blocco della pipeline, appena termina, chiama questo prima del
git commit. Se ritorna PASS/WARN il commit procede; se ritorna FAIL (exit 2) il
blocco si BLOCCA (non pusha quel contenuto) ma la pipeline va avanti col blocco
successivo. Fallire un pezzo non deve far saltare il resto.

Uso:
  python3 sanity_check.py <scope>

Scope supportati (uno per blocco della Fase A, piu' quelli della Fase B):
  standings   -> src/data/standings-*.json
  h2h         -> src/data/h2h.json
  news        -> src/content/news/*.md modificati
  entities    -> src/data/entities.json + sameAs sui profili
  profiles    -> src/content/{giocatori,tornei}-profilo/*.md modificati
  articles    -> src/content/articoli/*.md modificati (Fase B)
  recap       -> ultimo weekly recap (Fase A, lun)
  all         -> tutti i precedenti

Exit code:
  0 = PASS (deploy OK)
  1 = WARN (deploy OK, alert nei log)
  2 = FAIL (BLOCCA il deploy di questo blocco; pipeline prosegue)

Flag:
  --files F1 F2   file specifici da validare (override della scansione di default)
  --json          output machine-readable
  --since REF     usa git per prendere solo i file cambiati rispetto a REF (es. HEAD)

Nulla qui richiede rete o API. Zero dipendenze esterne oltre a Python stdlib.
"""
from __future__ import annotations
import json, re, sys, argparse, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'src/data'
NEWS = ROOT / 'src/content/news'
PLAYERS = ROOT / 'src/content/giocatori-profilo'
TOURS = ROOT / 'src/content/tornei-profilo'
ARTS = ROOT / 'src/content/articoli'
COVERS = ROOT / 'public/covers'

EM_DASH = '—'        # - vietato dallo stile della redazione
EN_DASH = '–'        # anche questo da normalizzare in ASCII '-'
APOSTR_BAD = re.compile(r"\b([aeiouAEIOU])'( |,|\.|$)")  # es: po' bene -> po' bene (euristica)

# ---------- utilities ----------

def _read(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8')
    except Exception:
        return ''

def _frontmatter(txt: str) -> dict:
    """Estrae il blocco frontmatter YAML (---...---) in dict molto permissivo."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', txt, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ':' not in line or line.startswith(' '):
            continue
        k, _, v = line.partition(':')
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm

def _git_changed(since: str, prefix: str | None = None) -> list[Path]:
    """File tracciati modificati (staged+unstaged) rispetto a <since> (es. HEAD)."""
    try:
        out = subprocess.check_output(['git', 'diff', '--name-only', since, '--'], cwd=ROOT, text=True)
        files = [ROOT / l.strip() for l in out.splitlines() if l.strip()]
        out2 = subprocess.check_output(['git', 'diff', '--name-only', '--cached'], cwd=ROOT, text=True)
        files += [ROOT / l.strip() for l in out2.splitlines() if l.strip()]
        out3 = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True)
        files += [ROOT / l.strip() for l in out3.splitlines() if l.strip()]
        if prefix:
            files = [f for f in files if str(f.relative_to(ROOT)).startswith(prefix)]
        return sorted(set(files))
    except Exception:
        return []

# ---------- checks ----------

def check_json(path: Path, required_keys: tuple[str, ...] = ()) -> tuple[str, str]:
    if not path.exists():
        return ('FAIL', f'{path.name} non esiste')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        return ('FAIL', f'{path.name} non e\' JSON valido: {e}')
    if isinstance(data, dict):
        miss = [k for k in required_keys if k not in data]
        if miss:
            return ('WARN', f'{path.name} manca chiavi: {miss}')
        if not data:
            return ('WARN', f'{path.name} e\' vuoto')
    elif isinstance(data, list) and not data:
        return ('WARN', f'{path.name} e\' una lista vuota')
    return ('PASS', f'{path.name} OK ({len(data)} elementi)')


def check_markdown(path: Path, required_fm: tuple[str, ...]) -> list[tuple[str, str]]:
    """Valida un singolo MD. Ritorna lista (level, msg)."""
    out: list[tuple[str, str]] = []
    if not path.exists():
        return [('FAIL', f'{path.name} non esiste')]
    txt = _read(path)
    if not txt.startswith('---'):
        out.append(('FAIL', f'{path.name}: frontmatter mancante (prima riga != ---)'))
        return out
    fm = _frontmatter(txt)
    miss = [k for k in required_fm if not fm.get(k)]
    if miss:
        out.append(('FAIL', f'{path.name}: frontmatter manca campi {miss}'))
    # Stile: em dash vietato
    if EM_DASH in txt:
        out.append(('WARN', f'{path.name}: trattino lungo (em dash) presente'))
    if EN_DASH in txt:
        out.append(('WARN', f'{path.name}: en dash (–) presente'))
    # Cover: se dichiarata, il file deve esistere
    cov = fm.get('cover_image') or ''
    if cov.startswith('/'):
        p = ROOT / 'public' / cov.lstrip('/')
        if not p.exists():
            out.append(('WARN', f'{path.name}: cover_image non esiste: {cov}'))
    # Slug coerenza (filename vs slug_profilo)
    slug_fm = fm.get('slug_profilo') or fm.get('slug') or ''
    if slug_fm and path.stem != slug_fm:
        out.append(('WARN', f'{path.name}: slug nel frontmatter != filename ({slug_fm})'))
    if not out:
        out.append(('PASS', f'{path.name} OK'))
    return out


# ---------- scopes ----------

def scope_standings(files: list[Path] | None = None) -> list[tuple[str, str]]:
    out = []
    for name in ('standings-atp.json', 'standings-wta.json', 'standings-atp-ext.json', 'standings-wta-ext.json'):
        p = DATA / name
        out.append(check_json(p))
    return out


def scope_h2h(files: list[Path] | None = None) -> list[tuple[str, str]]:
    return [check_json(DATA / 'h2h.json')]


def scope_entities(files: list[Path] | None = None) -> list[tuple[str, str]]:
    out = [check_json(DATA / 'player_entities.json')]
    return out


def scope_news(files: list[Path] | None = None) -> list[tuple[str, str]]:
    out = []
    targets = files or sorted(NEWS.glob('*.md'))
    for p in targets:
        if not str(p).startswith(str(NEWS)):
            continue
        out.extend(check_markdown(p, required_fm=('titolo', 'data', 'categoria')))
    if not out:
        out.append(('PASS', 'news: nessun file da validare'))
    return out


def scope_profiles(files: list[Path] | None = None) -> list[tuple[str, str]]:
    out = []
    targets = files or (list(PLAYERS.glob('*.md')) + list(TOURS.glob('*.md')))
    for p in targets:
        if not (str(p).startswith(str(PLAYERS)) or str(p).startswith(str(TOURS))):
            continue
        out.extend(check_markdown(p, required_fm=('nome', 'slug_profilo', 'intro', 'descrizione')))
    if not out:
        out.append(('PASS', 'profili: nessun file da validare'))
    return out


def scope_articles(files: list[Path] | None = None) -> list[tuple[str, str]]:
    """Validator per articoli pronostico (Fase B). Esclude recap/manifesto."""
    out = []
    targets = files or sorted(ARTS.glob('*.md'))
    for p in targets:
        if not str(p).startswith(str(ARTS)):
            continue
        name = p.stem
        if 'pronostico-analisi' in name:
            # Articolo di pronostico: schema completo
            out.extend(check_markdown(p, required_fm=(
                'titolo', 'data', 'autore', 'torneo', 'categoria',
                'giocatore1', 'giocatore2', 'verdetto', 'descrizione', 'cover_image'
            )))
        else:
            # Recap, manifesto, special: schema minimo
            out.extend(check_markdown(p, required_fm=('titolo', 'data', 'autore')))
    if not out:
        out.append(('PASS', 'articoli: nessun file da validare'))
    return out


def scope_recap(files: list[Path] | None = None) -> list[tuple[str, str]]:
    """Weekly recap finisce come articolo con tag recap: lo pescaamo da li."""
    out = []
    targets = files or sorted(ARTS.glob('*recap*.md'))
    if not targets:
        return [('PASS', 'recap: nessun file (tipico non-lunedi)')]
    for p in targets:
        out.extend(check_markdown(p, required_fm=('titolo', 'data', 'autore', 'descrizione')))
    return out


SCOPES = {
    'standings': scope_standings,
    'h2h':       scope_h2h,
    'news':      scope_news,
    'entities':  scope_entities,
    'profiles':  scope_profiles,
    'articles':  scope_articles,
    'recap':     scope_recap,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('scope', choices=list(SCOPES) + ['all'])
    ap.add_argument('--files', nargs='*', help='File specifici da validare')
    ap.add_argument('--since', help='Prendi solo file git-changed rispetto a questa ref')
    ap.add_argument('--json', action='store_true', help='Output JSON')
    args = ap.parse_args()

    files = [Path(f).resolve() for f in (args.files or [])] or None

    # Se --since e nessun --files: autoselect dai file cambiati
    if args.since and not files:
        prefix = {
            'news':     'src/content/news/',
            'profiles': 'src/content/giocatori-profilo/',
            'articles': 'src/content/articoli/',
        }.get(args.scope, None)
        files = _git_changed(args.since, prefix=prefix) or None

    results: list[tuple[str, str]] = []
    scopes = [args.scope] if args.scope != 'all' else list(SCOPES)
    for s in scopes:
        results.extend(SCOPES[s](files))

    fails = sum(1 for lvl, _ in results if lvl == 'FAIL')
    warns = sum(1 for lvl, _ in results if lvl == 'WARN')
    passes = sum(1 for lvl, _ in results if lvl == 'PASS')

    if args.json:
        print(json.dumps({
            'scope': args.scope,
            'pass': passes, 'warn': warns, 'fail': fails,
            'items': [{'level': l, 'msg': m} for l, m in results],
        }, ensure_ascii=False, indent=2))
    else:
        for lvl, msg in results:
            marker = {'PASS': '  ✓', 'WARN': '  ⚠', 'FAIL': '  ✗'}[lvl]
            print(f'{marker} [{lvl}] {msg}')
        verdict = 'FAIL' if fails else ('WARN' if warns else 'PASS')
        print(f'[sanity-check:{args.scope}] verdetto={verdict} pass={passes} warn={warns} fail={fails}')

    if fails:
        return 2
    if warns:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
