#!/usr/bin/env python3
"""Guardia pre-commit sui profili (giocatori + tornei).

Un SINGOLO profilo malformato (prima riga != '---', tipicamente il JSON grezzo
del modello dentro un fence ```json invece della frontmatter YAML) fa fallire
`astro build` sull'intera collezione -> Cloudflare non pubblica nulla di nuovo
-> deploy bloccato in silenzio (successo il 14/11: roman-andres-burruchaga.md,
residuo di un backfill glitchato, trascinato nel commit dalla pipeline).

Questa guardia gira PRIMA del `git add` in daily.sh:
- se il file contiene un oggetto JSON completo, lo riconverte in frontmatter
  valida (stessa logica del generatore, `_write_frontmatter`);
- se non e' riparabile, lo rimuove dal commit (git rm) cosi' non raggiunge main.

Non blocca mai la pipeline: exit 0 sempre. Idempotente (sui profili gia' validi
non fa nulla).

Uso:
  python3 guard_profiles.py            # scansiona entrambe le collezioni
  python3 guard_profiles.py --dry-run  # segnala soltanto, non tocca niente
"""
from __future__ import annotations
import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import generate_profiles as gp

ROOT = Path(__file__).resolve().parent.parent
DIRS = [ROOT / 'src/content/giocatori-profilo', ROOT / 'src/content/tornei-profilo']
# Campi minimi richiesti dallo schema di ENTRAMBE le collezioni (content/config.ts)
REQUIRED = ('nome', 'slug_profilo', 'intro', 'descrizione')


def _first_line(path: Path) -> str:
    try:
        txt = path.read_text()
    except Exception:
        return ''
    for line in txt.splitlines():
        if line.strip():
            return line.strip()
    return ''


def repair(path: Path) -> bool:
    """Prova a riconvertire un JSON grezzo in frontmatter valida. True se riuscito."""
    try:
        raw = path.read_text()
    except Exception:
        return False
    m = re.search(r'\{.*\}', raw, re.S)  # dal primo { all'ultimo }
    if not m:
        return False
    try:
        data = json.loads(m.group(0))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    body = data.get('corpo_markdown') or ''
    fm = {k: v for k, v in data.items() if k != 'corpo_markdown'}
    fm.setdefault('slug_profilo', path.stem)
    fm.setdefault('pubblicato', True)
    if not all(str(fm.get(k) or '').strip() for k in REQUIRED):
        return False
    gp._write_frontmatter(path, fm, body)
    return _first_line(path) == '---'


def main():
    dry = '--dry-run' in sys.argv[1:]
    fixed = removed = bad = 0
    for d in DIRS:
        if not d.exists():
            continue
        for path in sorted(d.glob('*.md')):
            if _first_line(path) == '---':
                continue
            bad += 1
            print(f'[guard] profilo malformato: {path.relative_to(ROOT)}', flush=True)
            if dry:
                continue
            if repair(path):
                print('[guard]   -> RIPARATO (JSON -> frontmatter)', flush=True)
                fixed += 1
            else:
                subprocess.run(['git', 'rm', '-f', '--ignore-unmatch', str(path)],
                               cwd=ROOT, capture_output=True)
                if path.exists():
                    try:
                        path.unlink()
                    except Exception:
                        pass
                print('[guard]   -> NON riparabile: RIMOSSO dal commit', flush=True)
                removed += 1
    if bad == 0:
        print('[guard] profili OK: nessun malformato.', flush=True)
    else:
        print(f'[guard] profili malformati: {bad} ({fixed} riparati, {removed} rimossi)', flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
