#!/usr/bin/env python3
"""Audit periodico del SET INDICIZZATO (prevenzione scaled-content penalty).

Lezione da PickForMe: una penalty "scaled content abuse" nasce quando il
footprint di pagine thin programmatiche indicizzate cresce troppo. Qui i
pronostici sono effimeri e si accumulano: due difese lo frenano
(backend/noindex_policy.py = qualita', src/lib/noindex.js = eta' 30gg). Questo
script le fotografa e AVVISA se qualcosa sfugge, cosi' il problema si vede
PRIMA, non dopo settimane (fu quello il costo vero su PickForMe).

Cosa guarda (solo collezione `articoli`, i pronostici = la superficie a rischio):
- quanti articoli totali, quanti noindex-qualita', quanti noindex-eta' (>30gg),
  quanti ancora INDICIZZATI;
- WARNING se gli indicizzati superano una soglia sana (il tetto naturale della
  regola 30gg e' ~6/gg x 30 = ~180; oltre ~250 c'e' qualcosa che non frena);
- WARNING se la quota noindex scende troppo (troppa roba indicizzata);
- WARNING se un articolo indicizzato ha > 30 giorni (incoerenza: la regola eta'
  non sta mordendo -> il sito non ribuilda da giorni).

Non blocca nulla: exit 0 sempre. Pensato per il log giornaliero di daily.sh e
per un controllo a mano. Output anche in JSON con --json.
"""
from __future__ import annotations
import json, re, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / 'src/content/articoli'

AGE_DAYS = 30                 # deve combaciare con NOINDEX_AGE_DAYS di src/lib/noindex.js
WARN_INDEXED_MAX = 250        # oltre = footprint pronostici troppo grande
WARN_NOINDEX_RATIO_MIN = 0.45 # sotto = troppa roba indicizzata rispetto al totale


def _parse(path: Path):
    t = path.read_text()
    md = re.search(r'^data:\s*"?(\d{4}-\d{2}-\d{2})', t, re.M)
    noidx = bool(re.search(r'^noindex:\s*true', t, re.M))
    pub = bool(re.search(r'^pubblicato:\s*false', t, re.M))
    date = datetime.date.fromisoformat(md.group(1)) if md else None
    return date, noidx, pub


def main():
    as_json = '--json' in sys.argv[1:]
    today = datetime.date.today()
    cut = today - datetime.timedelta(days=AGE_DAYS)

    tot = q_noindex = age_noindex = indexed = 0
    indexed_stale = []  # indicizzati ma > 30gg (incoerenza)
    for f in sorted(ART.glob('2026-*.md')):
        if 'benvenuti' in f.name:
            continue
        date, noidx, unpub = _parse(f)
        if unpub or not date:
            continue
        tot += 1
        if noidx:
            q_noindex += 1
        elif date < cut:
            age_noindex += 1
        else:
            indexed += 1
        if not noidx and date < cut:
            indexed_stale.append(f.stem)  # dovrebbe essere 0 (la regola eta' li esclude)

    noindex_tot = q_noindex + age_noindex
    ratio = (noindex_tot / tot) if tot else 0.0

    warnings = []
    if indexed > WARN_INDEXED_MAX:
        warnings.append(f'footprint indicizzato alto: {indexed} pronostici (soglia {WARN_INDEXED_MAX}) -> valuta di abbassare KEEP_ATP/KEEP_WTA in noindex_policy.py o la finestra eta')
    if ratio < WARN_NOINDEX_RATIO_MIN:
        warnings.append(f'quota noindex bassa: {ratio:.0%} (minimo sano {WARN_NOINDEX_RATIO_MIN:.0%}) -> troppa superficie indicizzata')
    # indexed_stale e' solo un segnale di build vecchia, non un rischio di per se'
    if len(indexed_stale) > 20:
        warnings.append(f'{len(indexed_stale)} articoli indicizzati > {AGE_DAYS}gg: il sito potrebbe non ribuildare da giorni (la regola eta e build-time)')

    report = {
        'data': today.isoformat(),
        'totale_pronostici': tot,
        'indicizzati': indexed,
        'noindex_qualita': q_noindex,
        'noindex_eta_30gg': age_noindex,
        'quota_noindex': round(ratio, 3),
        'warnings': warnings,
    }

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f'[seo-guard] pronostici: {tot} totali | {indexed} indicizzati | '
              f'{q_noindex} noindex-qualita | {age_noindex} noindex-eta(>{AGE_DAYS}gg) | '
              f'quota noindex {ratio:.0%}', flush=True)
        if warnings:
            for w in warnings:
                print(f'[seo-guard] ⚠ {w}', flush=True)
        else:
            print('[seo-guard] OK: footprint indicizzato sotto controllo.', flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
