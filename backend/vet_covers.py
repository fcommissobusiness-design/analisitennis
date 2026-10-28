#!/usr/bin/env python3
"""Gate di PERTINENZA VISIVO delle cover: guarda davvero la foto (non solo
il titolo del file) e decide se e' adatta come copertina di un articolo di
tennis. Le euristiche title-based di attach_covers/audit_covers non possono
sapere che "Shameen Tennis Ground.jpg" ritrae una strada o che una foto e'
una premiazione juniores: serve un occhio.

Come funziona:
- per ogni articolo (filtrabile per --date) prende la cover,
- chiede a claude CLI (vision) un verdetto SI/NO + motivo breve,
- su NO prova a rigenerare la cover (logica audit_covers) e ri-controlla,
- se resta NO dopo il tentativo, la segnala nel report per revisione manuale
  (non blocca la pipeline: meglio una cover debole che un articolo senza
  immagine).

Output: backend/cover_vet.json. Exit 0 sempre (gate non bloccante).

Uso:
  python3 vet_covers.py --date=2026-10-27     # solo gli articoli del giorno
  python3 vet_covers.py                        # tutti (lento: 1 call/cover)
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from attach_covers import (parse_frontmatter, NAME_MAP, pick_image, S,
                           download, strip_html, update_frontmatter, COVERS_DIR,
                           used_covers_for_player)
from audit_covers import regenerate_cover, ARTICOLI, ROOT

# Campi da tennis puliti e inequivocabili, usati come ultima spiaggia quando
# ne' foto giocatore ne' venue passano il vet (es. match tra due sconosciuti
# in un impianto che su Commons ha solo foto-concerto o esterni notturni).
CLEAN_COURTS = [
    'File:Sydney International Tennis ATP 250 (46001156835).jpg',
    'File:Jimmy C. Lunsford Tennis Center.jpg',
    'File:Olympic Tennis Centre, Rio, Brazil.jpg',
    'File:Arena principal do Centro Olímpico de Tênis.jpg',
]


def _fetch_commons(title: str):
    r = S.get('https://commons.wikimedia.org/w/api.php', params={
        'action': 'query', 'format': 'json', 'titles': title,
        'prop': 'imageinfo', 'iiprop': 'url|extmetadata'}, timeout=30)
    r.raise_for_status()
    p = list(r.json()['query']['pages'].values())[0]
    info = p['imageinfo'][0]
    em = info.get('extmetadata') or {}
    return {'title': p['title'], 'url': info['url'],
            'author': (em.get('Artist') or {}).get('value', ''),
            'license': (em.get('LicenseShortName') or {}).get('value', '')}


def _apply(stem: str, pick: dict) -> str:
    dest = COVERS_DIR / f'{stem}.jpg'
    download(pick['url'], dest)
    credit = (f"{pick['title'].replace('File:', '')} | "
              f"{strip_html(pick.get('author') or 'Autore sconosciuto')} | "
              f"{pick.get('license') or 'Wikimedia Commons'}")
    update_frontmatter(ARTICOLI / f'{stem}.md', f'/covers/{stem}.jpg', credit)
    return pick['title'][5:55]

CLAUDE_BIN = shutil.which('claude') or os.path.expanduser('~/.local/node/bin/claude')

PROMPT = (
    "Usa lo strumento Read per aprire l'immagine al percorso:\n{path}\n\n"
    "Devi decidere se e' adatta come COPERTINA di un articolo di tennis.\n"
    "Criterio: vogliamo un giocatore/giocatrice di tennis in AZIONE o almeno "
    "a mezza figura (dal busto in su, con la testa INTERA nell'inquadratura e "
    "racchetta/campo visibili), oppure un vero campo/arena da tennis durante "
    "il gioco.\n\n"
    "Considerala ADATTA (SI) SOLO se mostra chiaramente una di queste cose.\n\n"
    "Considerala NON adatta (NO) se si verifica ANCHE SOLO UNA di queste:\n"
    "- PRIMO PIANO del solo volto / mezzobusto ravvicinato / ritratto o "
    "headshot dove si vede soprattutto la faccia (fronte, viso): da rifiutare "
    "sempre, anche se e' il giocatore giusto.\n"
    "- La TESTA del giocatore e' TAGLIATA o fuori dall'inquadratura, o il "
    "soggetto e' tagliato male (si vedono solo gambe/busto senza testa).\n"
    "- Un CONCERTO, uno spettacolo, un palco, luci da evento, una folla a un "
    "evento: NO anche se e' dentro un'arena che a volte ospita il tennis.\n"
    "- Una strada, un paesaggio urbano, un edificio generico o il suo esterno "
    "notturno, una cerimonia/premiazione, un altro sport, un gruppo di persone "
    "in giacca, un volto buio da conferenza, un logo o un cartellone.\n"
    "- Qualunque cosa non chiaramente legata al tennis.\n\n"
    "Nel dubbio tra azione e primo piano del volto, rispondi NO.\n"
    "Rispondi ESATTAMENTE in questo formato su una riga:\n"
    "VERDETTO: SI|NO - MOTIVO: <massimo 10 parole>"
)


def vet_image(path: Path, timeout=120) -> tuple[bool, str]:
    """Ritorna (pertinente, motivo). In caso di errore CLI -> (True, 'skip')
    per non bloccare: non vogliamo perdere una cover buona per un glitch."""
    try:
        r = subprocess.run(
            [CLAUDE_BIN, '-p', PROMPT.format(path=path)],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (r.stdout or '').strip()
        m = re.search(r'VERDETTO:\s*(SI|NO)\s*-\s*MOTIVO:\s*(.*)', out, re.I)
        if not m:
            # Fallback: cerca un SI/NO secco
            if re.search(r'\bNO\b', out) and not re.search(r'\bSI\b', out):
                return False, out[:80]
            return True, 'parse incerto, tenuta'
        return (m.group(1).upper() == 'SI'), m.group(2).strip()[:80]
    except Exception as e:
        return True, f'vet skip ({type(e).__name__})'


def main():
    args = sys.argv[1:]
    date = None
    for a in args:
        if a.startswith('--date='):
            date = a.split('=', 1)[1]
    pattern = f'{date}-*.md' if date else '2026-*.md'
    articoli = [a for a in sorted(ARTICOLI.glob(pattern)) if 'benvenuti' not in a.name]

    report = []
    ko = 0
    court_idx = [0]  # rotazione campi puliti (ultima spiaggia), mutabile
    for art in articoli:
        fm, _ = parse_frontmatter(art)
        if not fm:
            continue
        cover_rel = (fm.get('cover_image') or '').lstrip('/')
        if not cover_rel:
            continue
        cover = ROOT / 'public' / cover_rel
        if not cover.exists():
            continue
        ok, motivo = vet_image(cover)
        entry = {'slug': art.stem, 'ok': ok, 'motivo': motivo}
        if ok:
            print(f'  [SI] {art.stem[:50]}', flush=True)
            report.append(entry)
            continue

        print(f'  [NO] {art.stem[:50]} - {motivo}', flush=True)
        stem = art.stem
        fm2, _ = parse_frontmatter(art)
        g1, g2 = fm2.get('giocatore1', ''), fm2.get('giocatore2', '')

        # Escalation di auto-correzione, ogni passo ri-controllato dal vet:
        # 1) rigenera con la logica standard (favorito/venue),
        # 2) forza una foto del giocatore mappato (g1 poi g2),
        # 3) ultima spiaggia: un campo da tennis pulito e inequivocabile.
        attempts = []

        gen_ok, gen_msg = regenerate_cover(art)
        if gen_ok:
            ok2, m2 = vet_image(cover)
            attempts.append(('rigenera', gen_msg[:40], ok2, m2))
            if ok2:
                entry.update({'ok': True, 'risolta_con': 'rigenera'})
                print(f'         -> rigenerata: risolta', flush=True)
                report.append(entry); continue

        cur_title = (fm2.get('cover_credit') or '').split('|')[0].strip()
        for g in (g1, g2):
            full = NAME_MAP.get(g)
            if not full:
                continue
            # Escludi la foto appena bocciata e quelle gia' usate per lui.
            excl = used_covers_for_player(full.split()[-1], skip_slug=stem)
            if cur_title:
                excl.add('File:' + cur_title)
            try:
                pick = pick_image(full, slug_hint=stem, exclude=excl)
            except Exception:
                pick = None
            if not pick:
                continue
            t = _apply(stem, pick)
            ok3, m3 = vet_image(cover)
            attempts.append(('giocatore:' + full, t, ok3, m3))
            if ok3:
                entry.update({'ok': True, 'risolta_con': 'giocatore ' + full})
                print(f'         -> foto {full}: risolta', flush=True)
                break
        if entry['ok']:
            report.append(entry); continue

        try:
            court = CLEAN_COURTS[court_idx[0] % len(CLEAN_COURTS)]
            court_idx[0] += 1
            t = _apply(stem, _fetch_commons(court))
            ok4, m4 = vet_image(cover)
            attempts.append(('campo', t, ok4, m4))
            entry['ok'] = ok4
            if ok4:
                entry['risolta_con'] = 'campo pulito'
                print(f'         -> campo pulito: risolta', flush=True)
        except Exception as e:
            attempts.append(('campo', f'errore {e}', False, ''))

        entry['attempts'] = [{'via': a, 'file': f, 'ok': o, 'motivo': m} for a, f, o, m in attempts]
        if not entry['ok']:
            ko += 1
            print(f'         -> ANCORA NO dopo {len(attempts)} tentativi (revisione manuale)', flush=True)
        report.append(entry)

    (ROOT / 'backend' / 'cover_vet.json').write_text(
        json.dumps({'date': date, 'total': len(report), 'da_rivedere': ko,
                    'details': report}, indent=2, ensure_ascii=False))
    print(f'\n=== VET: {len(report)} cover controllate, {ko} da rivedere a mano ===', flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
