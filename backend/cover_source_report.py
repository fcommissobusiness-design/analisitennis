"""Report fonte delle cover per una data: P18(entity) / foto-giocatore(ricerca)
/ venue-neutro. Misura l'effetto del fix anti-cover-sbagliata.
Uso: python3 cover_source_report.py YYYY-MM-DD   (default: oggi)
"""
import json, re, sys, unicodedata
from pathlib import Path
from datetime import date
ROOT = Path("/Users/filippocommisso/analisitennis")
ART = ROOT/"src/content/articoli"
ENT = json.loads((ROOT/"src/data/player_entities.json").read_text())
# nome(norm) -> slug, e slug -> image, dai profili
def norm(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c)!='Mn')
    return re.sub(r'[^a-z]','',s.lower())
name2slug = {}
for f in (ROOT/"src/content/giocatori-profilo").glob("*.md"):
    t=f.read_text()
    mn=re.search(r'^nome:\s*"?(.*?)"?\s*$',t,re.M); ms=re.search(r'^slug_profilo:\s*"?(.*?)"?\s*$',t,re.M)
    if mn and ms: name2slug[norm(mn.group(1))]=ms.group(1).strip()
def slug_of(abbrev):
    # prova nome completo, poi iniziale+cognome univoco
    s=name2slug.get(norm(abbrev))
    if s: return s
    parts=abbrev.replace('.',' ').split()
    if len(parts)<2: return None
    sur=norm(parts[-1]); ini=norm(parts[0])[:1]
    cand=[sl for nm,sl in name2slug.items() if nm.endswith(sur) and nm[:1]==ini]
    return cand[0] if len(cand)==1 else None
def p18_of(abbrev):
    s=slug_of(abbrev); return (ENT.get(s) or {}).get("image") if s else None
d = sys.argv[1] if len(sys.argv)>1 else date.today().isoformat()
def fm(path,k):
    m=re.search(rf'^{k}:\s*"?(.*?)"?\s*$',path.read_text(),re.M); return m.group(1) if m else ""
rows=[]
for f in sorted(ART.glob(f"{d}-*.md")):
    g1=fm(f,"giocatore1"); g2=fm(f,"giocatore2"); cf=fm(f,"cover_file")
    p1,p2=p18_of(g1),p18_of(g2)
    cfn=re.sub(r'^File:','',cf); 
    is_p18 = cf and (cf==p1 or cf==p2)
    sur1=norm(g1.split()[-1]) if g1 else ''; sur2=norm(g2.split()[-1]) if g2 else ''
    is_player = any(s and s in norm(cfn) for s in (sur1,sur2))
    src = "P18-entity" if is_p18 else ("foto-giocatore(ricerca)" if is_player else "venue/neutro")
    rows.append((src,g1,g2,cfn[:48]))
from collections import Counter
c=Counter(r[0] for r in rows)
print(f"=== Cover del {d}: {len(rows)} articoli ===")
for k in ("P18-entity","foto-giocatore(ricerca)","venue/neutro"):
    print(f"  {k:26} {c.get(k,0)}")
print()
for src,g1,g2,cf in rows:
    print(f"  [{src:24}] {g1} vs {g2}  <- {cf}")
