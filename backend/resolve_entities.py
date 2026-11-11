"""Aggancia i giocatori al knowledge graph: slug_profilo -> sameAs (Wikidata).

Step della pipeline (GEO/entity-linking). Legge i profili giocatore, risolve
su Wikidata SOLO quelli non ancora presenti in src/data/player_entities.json
(incrementale), e aggiorna il file. Emette sameAs verso Wikidata + Wikipedia +
sito ufficiale, piu' i dati ri-usabili dai template.

Principi:
  - Un sameAs sbagliato e' peggio di nessuno: match certo solo con doppio
    discriminante (occupation=tennista + anno nascita, o nazionalita').
  - Non deve MAI far fallire la pipeline: ogni errore e' assorbito, exit 0.
  - Cap per run (MAX_NEW): anche con molti profili nuovi non blocca il push;
    i rimanenti vengono risolti ai run successivi.
  - Rispetta Wikidata: batch getentities, backoff su 429, pausa tra giocatori.

Uso: python3 resolve_entities.py   (dalla cartella backend/)
"""
from __future__ import annotations
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILI = ROOT / "src/content/giocatori-profilo"
OUT = ROOT / "src/data/player_entities.json"

WD_API = "https://www.wikidata.org/w/api.php"
UA = "AnalisiTennis/1.0 (https://analisitennis.it; redazione@analisitennis.it) entity-linker"
TENNIS_OCCUPATIONS = {"Q10833314", "Q110639499"}  # tennis player, para tennis
MAX_NEW = 60           # risoluzioni nuove per run (il resto ai run successivi)
PAUSE = 0.6            # pausa tra giocatori (secondi)

NAZ_QID = {
    "Italia": "Q38", "Spagna": "Q29", "Francia": "Q142", "Germania": "Q183",
    "Stati Uniti": "Q30", "Russia": "Q159", "Serbia": "Q403", "Grecia": "Q41",
    "Ungheria": "Q28", "Norvegia": "Q20", "Ucraina": "Q212", "Gran Bretagna": "Q145",
    "Regno Unito": "Q145", "Australia": "Q408", "Canada": "Q16", "Argentina": "Q414",
    "Cechia": "Q213", "Rep. Ceca": "Q213", "Repubblica Ceca": "Q213", "Polonia": "Q36",
    "Danimarca": "Q35", "Croazia": "Q224", "Belgio": "Q31", "Paesi Bassi": "Q55",
    "Svizzera": "Q39", "Bielorussia": "Q184", "Kazakistan": "Q232", "Giappone": "Q17",
    "Cina": "Q148", "Brasile": "Q155", "Bulgaria": "Q219", "Tunisia": "Q948",
}


def _get(url: str) -> dict:
    headers = {"User-Agent": UA}
    delay = 2.0
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    return {}


def search_entities(name: str, limit=6) -> list[str]:
    q = urllib.parse.urlencode({
        "action": "wbsearchentities", "search": name, "language": "it",
        "uselang": "it", "format": "json", "limit": limit, "type": "item",
    })
    return [h["id"] for h in _get(f"{WD_API}?{q}").get("search", [])]


def get_entities_batch(qids: list[str]) -> dict:
    if not qids:
        return {}
    q = urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(qids), "format": "json",
        "props": "claims|sitelinks|labels",
    })
    return _get(f"{WD_API}?{q}").get("entities", {})


def _claim_values(ent: dict, prop: str) -> list:
    out = []
    for c in ent.get("claims", {}).get(prop, []):
        try:
            dv = c["mainsnak"]["datavalue"]["value"]
            out.append(dv["id"] if isinstance(dv, dict) and "id" in dv else dv)
        except (KeyError, TypeError):
            pass
    return out


def _birth_year(ent: dict) -> str | None:
    for c in ent.get("claims", {}).get("P569", []):
        try:
            return c["mainsnak"]["datavalue"]["value"]["time"][1:5]
        except (KeyError, TypeError):
            pass
    return None


def resolve(name: str, birth: str | None, nazionalita: str | None) -> dict | None:
    want_year = (birth or "")[:4] or None
    want_country = NAZ_QID.get((nazionalita or "").strip())
    qids = search_entities(name)
    ents = get_entities_batch(qids)
    for qid in qids:
        ent = ents.get(qid, {})
        if not (set(_claim_values(ent, "P106")) & TENNIS_OCCUPATIONS):
            continue
        yr = _birth_year(ent)
        countries = set(_claim_values(ent, "P27"))
        if want_year and yr:
            ok = (yr == want_year)
        elif want_country:
            ok = (want_country in countries)
        else:
            ok = True
        if not ok:
            continue
        sitelinks = ent.get("sitelinks", {})
        same = [f"https://www.wikidata.org/wiki/{qid}"]
        wiki_url = None
        for lang in ("itwiki", "enwiki"):
            if lang in sitelinks:
                title = sitelinks[lang]["title"].replace(" ", "_")
                sub = "it" if lang == "itwiki" else "en"
                wiki_url = f"https://{sub}.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                same.append(wiki_url)
                break
        for off in _claim_values(ent, "P856"):
            if isinstance(off, str):
                same.append(off)
        # P18 = immagine canonica su Wikimedia Commons di QUESTO giocatore.
        # La usa la selezione cover come prima scelta: foto della persona
        # giusta e verificata, cosi' non capita piu' di pescare un omonimo
        # non-tennista (artista, edificio) con la ricerca per cognome.
        image = None
        for img in _claim_values(ent, "P18"):
            if isinstance(img, str) and img.strip():
                image = "File:" + img.strip().replace("_", " ")
                break
        return {"wikidata": qid, "wikipedia": wiki_url, "sameAs": same, "image": image}
    return None


def read_fm(path: Path) -> dict:
    try:
        txt = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.search(r"^---\n(.*?)\n---", txt, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        mm = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip()
    return fm


def main() -> int:
    try:
        existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    except (OSError, json.JSONDecodeError):
        existing = {}
    files = sorted(PROFILI.glob("*.md"))
    tried = 0
    added = 0
    for f in files:
        if tried >= MAX_NEW:
            print(f"[entities] raggiunto cap {MAX_NEW} tentativi, il resto al prossimo run")
            break
        fm = read_fm(f)
        slug = fm.get("slug_profilo")
        nome = fm.get("nome")
        if not slug or not nome or slug in existing:
            continue
        try:
            r = resolve(nome, fm.get("data_nascita") or None, fm.get("nazionalita") or None)
        except Exception as e:
            print(f"[entities] errore {slug}: {e}")
            r = None
        tried += 1
        if r:
            entry = {"wikidata": r["wikidata"], "wikipedia": r["wikipedia"],
                     "sameAs": r["sameAs"]}
            if r.get("image"):
                entry["image"] = r["image"]
            existing[slug] = entry
            added += 1
            print(f"[entities] OK {slug} -> {r['wikidata']}"
                  + (f" [img]" if r.get("image") else ""))
        time.sleep(PAUSE)
    # scrittura atomica: tmp + replace, cosi' il json non e' mai mezzo scritto
    try:
        tmp = OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
        tmp.replace(OUT)
    except OSError as e:
        print(f"[entities] scrittura fallita: {e}")
        return 0
    print(f"[entities] totale agganciati: {len(existing)} (tentati {tried}, aggiunti {added} in questo run)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # mai far fallire la pipeline
        print(f"[entities] interrotto senza bloccare la pipeline: {e}")
        sys.exit(0)
