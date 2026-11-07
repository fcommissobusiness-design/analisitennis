#!/usr/bin/env python3
"""Migrazione una-tantum: accorcia i crediti foto esistenti a UNA riga e
popola il campo cover_file (nome file Commons) per il dedup globale.

Il vecchio formato era "NomeFileLunghissimo.jpg | Autore | Licenza", che su
mobile diventava una didascalia di 7-15 righe. Il nuovo credito e'
"Autore / Licenza / Wikimedia Commons" (come build_credit). Il nome del file
non si perde: va in cover_file (non mostrato), usato solo per non ripetere la
stessa foto tra articoli diversi.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attach_covers import build_credit, clean_author, strip_html  # noqa: E402

ARTICOLI = Path(__file__).resolve().parent.parent / 'src' / 'content' / 'articoli'


def process(path: Path) -> bool:
    raw = path.read_text()
    m = re.match(r'^---\n(.*?)\n---\n(.*)$', raw, re.S)
    if not m:
        return False
    fm_block, body = m.group(1), m.group(2)
    lines = fm_block.splitlines()

    credit = None
    for line in lines:
        mm = re.match(r'^cover_credit:\s*(.*)$', line)
        if mm:
            credit = mm.group(1).strip()
            if credit.startswith('"') and credit.endswith('"'):
                credit = credit[1:-1]
            break
    if not credit:
        return False

    segs = [s.strip() for s in credit.split('|')]
    title = segs[0] if segs else ''
    author = segs[1] if len(segs) > 1 else ''
    lic = segs[2] if len(segs) > 2 else ''
    # Se il credito e' gia' nel nuovo formato (nessuna '|', gia' corto) e
    # cover_file esiste, non tocchiamo nulla.
    gia_nuovo = '|' not in credit and len(credit) <= 115
    has_cover_file = any(l.startswith('cover_file:') for l in lines)
    if gia_nuovo and has_cover_file:
        return False

    pick = {'title': title, 'author': author, 'license': lic}
    new_credit = build_credit(pick) if '|' in credit else credit
    cover_file = title if title.startswith('File:') else ('File:' + title if title else '')

    out = []
    inserted_file = False
    for line in lines:
        if line.startswith('cover_credit:'):
            out.append(f'cover_credit: "{new_credit.replace(chr(34), chr(39))}"')
            if cover_file and not has_cover_file:
                out.append(f'cover_file: "{cover_file.replace(chr(34), chr(39))}"')
                inserted_file = True
        elif line.startswith('cover_file:'):
            out.append(f'cover_file: "{cover_file.replace(chr(34), chr(39))}"' if cover_file else line)
            inserted_file = True
        else:
            out.append(line)
    new_fm = '\n'.join(out)
    path.write_text(f'---\n{new_fm}\n---\n{body}')
    return True


def main():
    changed = 0
    for art in sorted(ARTICOLI.glob('2026-*.md')):
        try:
            if process(art):
                changed += 1
        except Exception as e:
            print(f'[warn] {art.name}: {e}')
    print(f'Crediti accorciati/aggiornati: {changed}')


if __name__ == '__main__':
    main()
