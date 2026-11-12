"""Backfill del flag `noindex` sugli articoli gia' pubblicati, con la stessa
policy di noindex_policy.should_noindex. Ricostruisce un match sintetico dal
frontmatter (categoria -> event_type_type, torneo, nomi giocatori); il round
non e' nel frontmatter (nessuna eccezione finale-500, impatto trascurabile).

Uso:
  python3 backfill_noindex.py            # DRY RUN: conta e mostra esempi
  python3 backfill_noindex.py --apply    # scrive il flag nei .md
"""
import re
import sys
from pathlib import Path

from noindex_policy import should_noindex

ART = Path(__file__).resolve().parent.parent / 'src' / 'content' / 'articoli'

CAT2TIPO = {
    'Slam': 'Grand Slam', 'Masters': 'Masters', 'Challenger': 'Challenger',
    'ATP': 'Atp Singles', 'WTA': 'Wta Singles', 'ITF': 'Itf Singles',
}


def parse_fm(txt):
    m = re.match(r'^---\n(.*?)\n---', txt, re.S)
    if not m:
        return None, None, None
    block = m.group(1)
    fm = {}
    for line in block.splitlines():
        mm = re.match(r'^([a-zA-Z0-9_]+):\s*(.*)$', line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return fm, block, m.end()


def decide(fm):
    match = {
        'event_type_type': CAT2TIPO.get(fm.get('categoria', ''), fm.get('categoria', '')),
        'tournament_name': fm.get('torneo', ''),
        'event_first_player': fm.get('giocatore1', ''),
        'event_second_player': fm.get('giocatore2', ''),
        'tournament_round': '',
    }
    return should_noindex(match)


def set_noindex(txt, want):
    """Inserisce/rimuove `noindex: true` nel frontmatter in modo idempotente."""
    has = re.search(r'^noindex:\s*true\s*$', txt, re.M)
    if want and not has:
        # inserisci dopo la riga pubblicato:
        return re.sub(r'(^pubblicato:.*$)', r'\1\nnoindex: true', txt, count=1, flags=re.M)
    if not want and has:
        return re.sub(r'^noindex:\s*true\s*\n', '', txt, count=1, flags=re.M)
    return txt


def main():
    apply = '--apply' in sys.argv
    files = [f for f in sorted(ART.glob('2026-*.md')) if 'benvenuti' not in f.name]
    ni, changed, esempi = 0, 0, []
    for f in files:
        txt = f.read_text()
        fm, _, _ = parse_fm(txt)
        if not fm:
            continue
        no, motivo = decide(fm)
        if no:
            ni += 1
            if len(esempi) < 14:
                esempi.append(f'  NOINDEX {f.stem[:60]} | {motivo}')
        new = set_noindex(txt, no)
        if new != txt:
            changed += 1
            if apply:
                f.write_text(new)
    print('\n'.join(esempi))
    print(f'\n=== {ni}/{len(files)} articoli -> noindex; {changed} file da modificare '
          f'({"APPLICATO" if apply else "DRY RUN"}) ===')


if __name__ == '__main__':
    main()
