"""Esporta la NAME_MAP (nomi abbreviati API -> nome completo) del backend in
src/data/name-map.json, cosi' il frontend (src/lib/hubs.js) la importa e usa
gli STESSI slug del backend. Elimina alla radice i profili duplicati
(es. 'b-shelton' vs 'ben-shelton') dovuti a mappe disallineate.

Va eseguito nella pipeline prima del commit: daily.sh lo lancia e `git add
src/data/*.json` lo include. Idempotente."""
import json
from pathlib import Path

from attach_covers import NAME_MAP

OUT = Path(__file__).resolve().parent.parent / 'src' / 'data' / 'name-map.json'


def main():
    # Ordinato per stabilita' del diff git.
    data = {k: NAME_MAP[k] for k in sorted(NAME_MAP)}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(f'[name-map] esportate {len(data)} voci in {OUT}')


if __name__ == '__main__':
    main()
