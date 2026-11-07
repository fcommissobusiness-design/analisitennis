#!/usr/bin/env python3
"""Riscrive le news gia' pubblicate nel nuovo formato piu' completo, IN PLACE.

Per ogni news esistente: ricostruisce la candidata dai campi salvati, la
RI-VERIFICA sul web (per raccogliere il contesto verificato), riscrive 3-5
paragrafi e passa il gate. Sovrascrive titolo/sommario/corpo/tag SOLO se la
verifica conferma e il gate passa. Mantiene lo stesso slug (URL stabile),
chiave, data e fonte: nessun link pubblicato si rompe.

Prudente: se una news non e' piu' riverificabile, la lascia com'e'.
Uso: python3 expand_news.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_news as fn  # noqa: E402

NEWS_DIR = fn.NEWS_DIR


def _parse(path: Path):
    raw = path.read_text()
    m = re.match(r'^---\n(.*?)\n---\n(.*)$', raw, re.S)
    if not m:
        return None, None, None
    fm_raw, body = m.group(1), m.group(2)
    fm = {}
    tags = []
    in_tag = False
    for line in fm_raw.splitlines():
        mt = re.match(r'^\s*-\s*"?(.*?)"?\s*$', line)
        if in_tag and mt:
            tags.append(mt.group(1))
            continue
        in_tag = False
        mm = re.match(r'^([a-zA-Z_0-9]+):\s*(.*)$', line)
        if mm:
            k, v = mm.group(1), mm.group(2).strip()
            if k == 'tag':
                in_tag = True
                continue
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            fm[k] = v
    fm['tag'] = tags
    return fm, body.strip(), raw


def _write(path: Path, fm: dict, corpo: str):
    lines = ['---',
             f'titolo: "{fm["titolo"].replace(chr(34), chr(39))}"',
             f'sommario: "{fm["sommario"].replace(chr(34), chr(39))}"',
             f'data: "{fm["data"]}"',
             'autore: "Redazione AnalisiTennis"',
             f'categoria: "{fm["categoria"]}"',
             f'chiave: "{fm["chiave"]}"',
             f'fonte_nome: "{fm.get("fonte_nome","").replace(chr(34), chr(39))}"',
             f'fonte_url: "{fm.get("fonte_url","")}"',
             'tag:']
    for t in fm.get('tag', []):
        lines.append(f'  - "{t.replace(chr(34), chr(39))}"')
    lines += [f'generato_il: "{fm.get("generato_il","")}"', 'pubblicato: true', '---', '', corpo]
    path.write_text('\n'.join(lines) + '\n')


def main():
    files = sorted(NEWS_DIR.glob('*.md'))
    print(f'news da valutare: {len(files)}')
    migliorate = 0
    for path in files:
        fm, body, raw = _parse(path)
        if not fm:
            continue
        # Gia' lunga (nuovo formato)? Conta i paragrafi del corpo.
        paragrafi = [p for p in re.split(r'\n\s*\n', body or '') if p.strip()]
        if len(paragrafi) >= 3 and len(body or '') > 600:
            print(f'  = {path.name[:50]}: gia estesa, salto')
            continue
        item = {
            'headline': fm.get('titolo', ''),
            'summary': fm.get('sommario', ''),
            'category': fm.get('categoria', 'altro'),
            'entities': fm.get('tag', []),
            'sources': [fm.get('fonte_url', '')] if fm.get('fonte_url') else [],
            'date': fm.get('data', ''),
        }
        print(f'  ~ {path.name[:50]}: riverifico...', flush=True)
        try:
            v = fn.verifica(item)
        except Exception as e:
            print(f'    verifica errore: {e}, lascio com\'e')
            continue
        if not v or v.get('verdict') != 'CONFERMATA':
            print('    non riconfermata, lascio com\'e')
            continue
        fatto = v.get('fatto_verificato', '')
        fonti = v.get('fonti_conferma', []) or []
        contesto = v.get('contesto_verificato', []) or []
        if not fatto or not fonti:
            print('    senza fatto/fonti, lascio com\'e')
            continue
        try:
            art = fn.scrivi(fatto, fonti, fm.get('categoria', 'altro'), contesto=contesto)
            g = fn.gate(fatto, fonti, art, contesto=contesto)
        except Exception as e:
            print(f'    scrittura/gate errore: {e}, lascio com\'e')
            continue
        if not g.get('ok'):
            print(f'    gate FALLITO ({g.get("problemi")}), lascio com\'e')
            continue
        nuovo_corpo = fn.normalizza(art['corpo_markdown'])
        if len(nuovo_corpo) <= len(body or ''):
            print('    nuovo corpo non piu lungo, lascio com\'e')
            continue
        fm['titolo'] = fn.normalizza(art['titolo'])
        fm['sommario'] = fn.normalizza(art.get('sommario', fm.get('sommario', '')))
        new_tags = [fn.normalizza(t) for t in (art.get('tag') or fm.get('tag', []))]
        fm['tag'] = new_tags or fm.get('tag', [])
        # fonte dalla riverifica se disponibile
        if fonti:
            fm['fonte_nome'] = fonti[0].get('nome', fm.get('fonte_nome', ''))
            fm['fonte_url'] = fonti[0].get('url', fm.get('fonte_url', ''))
        _write(path, fm, nuovo_corpo)
        migliorate += 1
        print(f'    MIGLIORATA ({len(paragrafi)} -> {len([p for p in re.split(chr(10)+chr(10), nuovo_corpo) if p.strip()])} parag.)')
    print(f'\n=== news migliorate: {migliorate}/{len(files)} ===')


if __name__ == '__main__':
    main()
