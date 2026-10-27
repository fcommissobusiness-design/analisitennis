#!/usr/bin/env python3
"""Utility per tenere le cover a misura web.

Problema storico: attach_covers.download() salvava il file ORIGINALE di
Wikimedia Commons senza ridimensionare. Risultato: cover da 9000+ px e
10-18 MB l'una (316 MB totali). Sul sito, con connessioni normali, la
foto impiega secondi a scaricare e la card mostra l'alt-text = sembra
"immagine rotta". Inoltre peggiora Core Web Vitals e il crawl budget.

Regola testata: una cover si vede al massimo a ~1200px (hero articolo) e
a ~440px (card home). 1600px lato lungo e JPEG qualita' 82 danno nitidezza
piena su retina restando sotto i ~350 KB. Questo modulo e' la fonte unica
della regola, importato sia dal batch one-shot sia dalla pipeline daily.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageOps

# Lato lungo massimo in px e qualita' JPEG. Non toccare senza motivo:
# sono il punto di equilibrio tra nitidezza su retina e peso.
MAX_LONG_SIDE = 1600
JPEG_QUALITY = 82
# Soglia oltre cui una cover e' considerata "troppo pesante" per il web.
# Usata dall'audit per decidere se ri-processare un file gia' pertinente.
MAX_BYTES = 400 * 1024  # 400 KB


def needs_resize(path: Path) -> bool:
    """True se il file supera il lato lungo max o il peso max."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return True
        with Image.open(path) as im:
            return max(im.size) > MAX_LONG_SIDE
    except Exception:
        # File illeggibile: lo trattiamo come da rigenerare, non da resize.
        return False


def ensure_web_size(path: Path, max_long: int = MAX_LONG_SIDE,
                    quality: int = JPEG_QUALITY) -> dict:
    """Ridimensiona la cover in-place a misura web, se serve.

    - rispetta l'orientamento EXIF e poi lo rimuove (altrimenti il browser
      puo' mostrare la foto ruotata),
    - converte in RGB (JPEG non supporta alpha/palette),
    - scala a `max_long` px sul lato lungo solo se piu' grande,
    - salva JPEG `quality`, optimize, progressive.

    Ritorna un dict con before/after per il log. Non solleva: in caso di
    errore ritorna {'ok': False, 'error': ...} cosi' la pipeline prosegue.
    """
    info = {'file': path.name, 'ok': True}
    try:
        before_bytes = path.stat().st_size
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)  # applica rotazione EXIF
            before_w, before_h = im.size
            if im.mode not in ('RGB',):
                im = im.convert('RGB')
            long_side = max(im.size)
            if long_side > max_long:
                scale = max_long / long_side
                new_size = (round(im.width * scale), round(im.height * scale))
                im = im.resize(new_size, Image.LANCZOS)
            im.save(path, 'JPEG', quality=quality, optimize=True,
                    progressive=True)
        after_bytes = path.stat().st_size
        info.update({
            'before': f'{before_w}x{before_h} {before_bytes // 1024}KB',
            'after': f'{im.width}x{im.height} {after_bytes // 1024}KB',
            'saved_kb': (before_bytes - after_bytes) // 1024,
        })
    except Exception as e:
        info['ok'] = False
        info['error'] = str(e)
    return info


def main():
    """Batch one-shot: ridimensiona TUTTE le cover in public/covers."""
    root = Path(__file__).resolve().parent.parent
    covers = sorted((root / 'public' / 'covers').glob('*.jpg'))
    tot_before = tot_after = 0
    changed = 0
    for c in covers:
        b = c.stat().st_size
        tot_before += b
        res = ensure_web_size(c)
        a = c.stat().st_size
        tot_after += a
        if res.get('ok') and res.get('saved_kb', 0) != 0:
            changed += 1
            print(f"  {c.name}: {res.get('before')} -> {res.get('after')}")
        elif not res.get('ok'):
            print(f"  [ERR] {c.name}: {res.get('error')}")
    print(f"\n{changed}/{len(covers)} cover ridotte. "
          f"Totale {tot_before // (1024*1024)}MB -> {tot_after // (1024*1024)}MB")


if __name__ == '__main__':
    main()
