"""Aggiunge agli articoli esistenti il campo probabilita' di vittoria calcolato
dal modello (numero preciso e variabile), leggendo verdetto + corpo dell'analisi
(che gia' contengono ranking, scontri diretti, forma, superficie). Serve a dare
agli articoli gia' pubblicati la stessa griglia precisa che la pipeline ora
genera di default. Idempotente: salta gli articoli che hanno gia' il campo.

Uso:
  python3 backfill_probabilita.py --date=YYYY-MM-DD    # solo quel giorno
  python3 backfill_probabilita.py --all                # tutti gli articoli-match
  python3 backfill_probabilita.py slug1 slug2 ...       # articoli specifici
"""
import re
import sys
import glob
from pathlib import Path

from generate_analysis import _claude_call

ART = Path(__file__).resolve().parent.parent / 'src' / 'content' / 'articoli'


def fm_val(testo, campo):
    m = re.search(rf'^{campo}:\s*"?([^"\n]+)"?\s*$', testo, re.M)
    return (m.group(1).strip() if m else '')


def stima(corpo, verdetto, g1, g2):
    prompt = (
        f"Sei un analista di tennis. Dal VERDETTO e dal CORPO dell'analisi qui "
        f"sotto, stima la PROBABILITA' DI VITTORIA del giocatore favorito tra "
        f"{g1} e {g2}. Deve essere un numero INTERO tra 50 e 82, calibrato sui "
        f"fatti citati (differenza di ranking, bilancio scontri diretti, forma "
        f"recente, resa sulla superficie). Numero PRECISO e specifico di questo "
        f"match (es. 57, 63, 71, 66), MAI un valore tondo di comodo. "
        f"Calibrazione: divario netto 68-81, divario sottile 55-65, equilibrio "
        f"50-54. Scegli SEMPRE un favorito (uno dei due), anche in equilibrio.\n\n"
        f"VERDETTO: {verdetto}\n\nCORPO:\n{corpo[:3500]}\n\n"
        f'Rispondi SOLO con questo JSON: {{"favorito": "Cognome", "percent": 63}}'
    )
    return _claude_call(prompt, timeout=180)


def process(slug):
    p = ART / f'{slug}.md'
    if not p.exists():
        print(f'  [skip] {slug}: non esiste'); return
    raw = p.read_text()
    if 'probabilita_percent:' in raw:
        print(f'  [ok] {slug}: gia presente'); return
    parts = raw.split('---', 2)
    if len(parts) < 3:
        print(f'  [skip] {slug}: frontmatter non valido'); return
    fmtxt, corpo = parts[1], parts[2]
    g1, g2 = fm_val(fmtxt, 'giocatore1'), fm_val(fmtxt, 'giocatore2')
    verdetto = fm_val(fmtxt, 'verdetto')
    if g1 == 'Redazione' or not g1 or not g2:
        print(f'  [skip] {slug}: editoriale/senza giocatori'); return
    try:
        r = stima(corpo, verdetto, g1, g2)
        fav = str(r.get('favorito', '')).strip()
        pct = int(round(float(str(r.get('percent', '')).strip().rstrip('%'))))
    except Exception as e:
        print(f'  [errore] {slug}: {e}'); return
    if not fav or not (50 <= pct <= 82):
        print(f'  [scarta] {slug}: valori non validi ({fav} {pct})'); return
    # Inserisci le due righe subito dopo 'verdetto:' nel frontmatter.
    new_fm = re.sub(r'(^verdetto:.*$)',
                    rf'\1\nprobabilita_favorito: "{fav}"\nprobabilita_percent: {pct}',
                    fmtxt, count=1, flags=re.M)
    p.write_text('---' + new_fm + '---' + corpo)
    print(f'  [fatto] {slug}: {fav} {pct}%')


def main():
    args = sys.argv[1:]
    slugs = []
    if any(a == '--all' for a in args):
        slugs = [Path(f).stem for f in glob.glob(str(ART / '*.md'))]
    elif any(a.startswith('--date=') for a in args):
        d = [a.split('=', 1)[1] for a in args if a.startswith('--date=')][0]
        slugs = [Path(f).stem for f in glob.glob(str(ART / f'{d}-*.md'))]
    else:
        slugs = [a for a in args if not a.startswith('--')]
    print(f'[backfill prob] {len(slugs)} articoli')
    for s in sorted(slugs):
        process(s)


if __name__ == '__main__':
    main()
