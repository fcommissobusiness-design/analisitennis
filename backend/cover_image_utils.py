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
# Larghezza MINIMA: Google Discover mostra le immagini "large" solo se larghe
# almeno 1200px. Le foto verticali dei giocatori spesso sono piu' strette, per
# questo si fa un leggero upscale (Lanczos) fino a 1200px di larghezza: cosi'
# diventano eleggibili senza cambiarne la composizione.
MIN_WIDTH = 1200
JPEG_QUALITY = 82
# WebP: ~30% piu' leggero del JPEG a parita' di qualita' visiva. Servito
# via <picture> con fallback JPEG. Migliora Core Web Vitals e Google Discover.
WEBP_QUALITY = 80
# Variante CARD: le card di home/oggi si vedono a ~440px CSS, ma finora
# scaricavano la cover piena da 1600px (~144 KB in WebP). Con 12 card
# rivelate insieme sono ~1,7 MB in un colpo: le immagini restano in coda e
# per qualche secondo il browser mostra l'alt-text = sembrano rotte.
# 800px copre il retina 2x su una card da 400px pesando ~3x meno.
CARD_WIDTH = 800
CARD_QUALITY = 76
CARD_SUFFIX = '-card.webp'


def card_path(path: Path) -> Path:
    """Percorso della variante card per una cover JPEG."""
    return path.with_name(path.stem + CARD_SUFFIX)


def ensure_card_variant(path: Path, im=None) -> bool:
    """Genera la variante card (WebP stretto) accanto alla cover.
    `im` opzionale: immagine gia' aperta/processata, per non riaprire il file.
    Non solleva: su errore ritorna False e la pipeline prosegue."""
    try:
        dest = card_path(path)
        if im is None:
            with Image.open(path) as src:
                src = ImageOps.exif_transpose(src)
                if src.mode != 'RGB':
                    src = src.convert('RGB')
                return _save_card(src, dest)
        return _save_card(im, dest)
    except Exception as e:
        print(f'  [warn] card variant fallita {path.name}: {e}')
        return False


def _save_card(im, dest: Path) -> bool:
    if im.width > CARD_WIDTH:
        scale = CARD_WIDTH / im.width
        im = im.resize((CARD_WIDTH, round(im.height * scale)), Image.LANCZOS)
    im.save(dest, 'WEBP', quality=CARD_QUALITY, method=6)
    return True
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
            # Garantisci larghezza >= MIN_WIDTH per l'eleggibilita' Discover
            # (upscale leggero solo se la foto e' piu' stretta).
            if im.width < MIN_WIDTH:
                scale = MIN_WIDTH / im.width
                im = im.resize((MIN_WIDTH, round(im.height * scale)), Image.LANCZOS)
            im.save(path, 'JPEG', quality=quality, optimize=True,
                    progressive=True)
            # Gemella WebP accanto al JPEG (stesso nome, estensione .webp).
            # Il JPEG resta la cover canonica (og:image/schema); il WebP e'
            # servito al browser via <picture> quando supportato.
            try:
                im.save(path.with_suffix('.webp'), 'WEBP', quality=WEBP_QUALITY, method=6)
            except Exception as e:
                print(f'  [warn] webp fallito {path.name}: {e}')
            # Variante stretta per le card di home/oggi (vedi CARD_WIDTH).
            ensure_card_variant(path, im.copy())
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
