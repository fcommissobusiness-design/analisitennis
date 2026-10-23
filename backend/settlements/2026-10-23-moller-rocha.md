---
name: settle-moller-rocha-20261023
description: 23/10/2026 — Settlement completo primo pick ufficiale AnalisiTennis.it. Moller d. Rocha 6-2 6-4 (Lisbon CH QF). Pronostico Rocha vinc SBAGLIATO. Statistiche complete per punto/set/giocatore.
metadata:
  node_type: memory
  type: project
  originSessionId: 370210bf-2b00-444d-bca7-14c86193664f
  modified: 2026-10-23T18:39:10.167Z
---

## Contesto
Primo pick ufficiale di AnalisiTennis.it, pubblicato in automatico via pipeline su `/articoli/2026-10-23-e-moller-vs-h-rocha-lisbon-pronostico-analisi`. Pronostico sportivo editoriale: "Oggi la può spuntare Rocha". Match giocato alle 16:05 ora italiana al Challenger di Lisbona (quarti di finale, terra battuta outdoor).

## Risultato autoritativo (API Tennis)
- **Winner**: E. Moller
- **Score finale set**: 2 - 0
- **Set 1**: 6-2 Moller
- **Set 2**: 6-4 Moller
- **Durata**: ~90 min (stimata, 18 game totali)

## Pronostico vs esito
- Nostro pronostico editoriale: **Oggi la può spuntare Rocha**
- Esito reale: **Moller vince 2-0 secco**
- Verdetto: **PRONOSTICO SBAGLIATO**
- Error-type: under-weighting dei precedenti diretti. H2H era 2-0 Moller (Lima 2024 2-0 + Braga 2025 2-1), tutti e due su calibro-tipo Rocha. Il motore ha dato peso eccessivo a (a) ranking Rocha più alto, (b) titolo Porto fresco, (c) home crowd portoghese. Il pattern "chi ha vinto gli ultimi 2 H2H consecutivi" avrebbe dovuto pesare di più. Da calibrare nel winprob.

## Statistiche per giocatore (match)

### E. Moller (vincitore)
| Voce | Valore |
|---|---|
| Ace | 1 |
| Doppi falli | 3 |
| Prima palla % | 70% |
| Pt 1a vinti | 60% (25/42) |
| Pt 2a vinti | 72% (13/18) |
| Break points salvati | 83% (5/6) |
| Pt 1a return vinti | 45% (19/42) |
| Pt 2a return vinti | 57% (12/21) |
| Break points convertiti | 57% (4/7) |
| Service Points Won | 63% (38/60) |
| Return Points Won | 48% (30/63) |
| **Total Points Won** | **55% (68/123)** |
| Service games won | 89% (8/9) |
| Return games won | 44% (4/9) |
| **Total games won** | **67% (12/18)** |

### H. Rocha (perdente)
| Voce | Valore |
|---|---|
| Ace | 3 |
| Doppi falli | 3 |
| Prima palla % | 67% |
| Pt 1a vinti | 57% (24/42) |
| Pt 2a vinti | 43% (9/21) |
| Break points salvati | 43% (3/7) |
| Pt 1a return vinti | 45% (19/42) |
| Pt 2a return vinti | 28% (5/18) |
| Break points convertiti | **17% (1/6)** |
| Service Points Won | 52% (33/63) |
| Return Points Won | 37% (22/60) |
| **Total Points Won** | **45% (55/123)** |
| Service games won | 56% (5/9) |
| Return games won | **11% (1/9)** |
| **Total games won** | **33% (6/18)** |

## Statistiche per SET

### Set 1 (Moller 6-2)
**Moller set-1**: 1a% 71% · pt1a 53% · pt2a 86% · BP salvati 100% (2/2) · BP convertiti 67% (2/3) · service games 100% (4/4) · return games 50% (2/4) · total pt 57% (30/53)

**Rocha set-1**: 1a% 64% · pt1a 56% · pt2a 44% · BP salvati 33% (1/3) · BP convertiti 0% (0/2) · service games 50% (2/4) · return games 0% (0/4) · total pt 43% (23/53)

### Set 2 (Moller 6-4)
**Moller set-2**: 1a% 69% · pt1a 64% · pt2a 64% · BP salvati 75% (3/4) · BP convertiti 50% (2/4) · service games 80% (4/5) · return games 40% (2/5) · total pt 54% (38/70) · 1 ace, 3 DF

**Rocha set-2**: 1a% 68% · pt1a 58% · pt2a 42% · BP salvati 50% (2/4) · BP convertiti 25% (1/4) · service games 60% (3/5) · return games 20% (1/5) · total pt 46% (32/70) · 2 ace, 2 DF · **1 match point salvato**

## Point-by-point sintesi
- Totale game disputati: 18
- Point-by-point disponibile per tutti i 18 game
- Set 1: Rocha ha tenuto solo 2 game, break subito nel game 3 (al servizio Rocha), consolidato nel game 5
- Match complessivo: 123 punti totali, Moller 68 (55%), Rocha 55 (45%)

## Chiavi tattiche emerse (post-mortem)

1. **Moller cinico sui break-point**: 83% salvati, 57% convertiti. Rocha disastroso: 43% salvati, 17% convertiti (1/6!). È la statistica che ha deciso il match in un contesto dove il hold+return era quasi pari (Moller service won 63% vs Rocha 52%, non enorme).

2. **Prima palla Rocha non ha funzionato**: 67% ma punti vinti solo 57% (basso per home su terra). Pattern-killer per il giocatore di casa su terra lenta.

3. **Seconda palla Moller devastante**: 72% punti vinti con seconda. Rocha col return non è riuscito a punire.

4. **Home crowd non ha compensato**: Rocha ha vinto solo 33% dei game totali (6/18). Il tifo di casa non ha pesato sui momenti chiave (break-point).

## Lezioni per calibrazione modello

- **Pattern "chi ha vinto gli ultimi 2 H2H consecutivi"** su calibro-simile = segnale FORTE, va pesato ~15-20% nel winprob, non 5-8% come fatto.
- **Ranking migliore non equivale a forma attuale** quando l'avversario ha pattern-dominanza H2H.
- **Home crowd pesa poco su clay-slow in challenger** quando l'avversario è già reduce da buoni match sulla stessa superficie-torneo (Moller aveva fatto F Braga + 2W Lisbon).
- **Break-point efficiency** come 6° stimatore ensemble: Rocha stagionale aveva BP% basso, dato che se integrato nel modello avrebbe abbassato il fair ulteriormente.

## Impatto sul blog
- Primo pick pubblicato = perso
- Articolo online: https://analisitennis.fcommisso-business.workers.dev/articoli/2026-10-23-e-moller-vs-h-rocha-lisbon-pronostico-analisi
- Verrà corredato da un recap post-match in futuro (feature da aggiungere al blog, non ancora implementata)

Collegato: [[tennis-blog-project]] · [[prompt-fasi-canonico]]
