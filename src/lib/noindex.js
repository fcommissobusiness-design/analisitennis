// Noindex "effettivo" di un articolo-pronostico, calcolato AL BUILD.
// Due regole in OR:
//   1) QUALITA' (match minori): deciso a monte da backend/noindex_policy.py e
//      scritto nel frontmatter -> data.noindex === true. Indicizza solo i match
//      che contano (marquee, giocatore top, miglior rank entro soglia, finali 500).
//   2) ETA' (prevenzione anti scaled-content): un pronostico e' EFFIMERO. Dopo
//      NOINDEX_AGE_DAYS giorni dalla pubblicazione non ha piu' valore di ricerca
//      e, restando indicizzato, diventa "pagina thin accumulata" = esattamente il
//      segnale che Google penalizza come scaled content. Quindi esce dall'indice
//      (resta PUBBLICATO e navigabile, link interni "follow": non si perde nulla
//      per gli utenti e per il GEO, si toglie solo il segnale a Google).
//
// Vale SOLO per la collezione `articoli` (i pronostici). Profili giocatore/torneo
// e hub sono evergreen e restano indicizzati per sempre: non passano di qui.
// Il sito ribuilda ogni giorno (pipeline) + a ogni push, quindi l'eta' e' sempre
// ricalcolata e un articolo diventa noindex entro ~1 giorno dal superamento soglia.
export const NOINDEX_AGE_DAYS = 30;

export function isNoindexArticle(data, now = Date.now()) {
  if (!data) return false;
  if (data.noindex === true) return true;            // regola 1: qualita'
  const raw = data.data || data.generato_il;          // regola 2: eta'
  if (!raw) return false;
  const pub = new Date(raw);
  if (isNaN(pub)) return false;
  const ageDays = (now - pub.valueOf()) / 86400000;
  return ageDays > NOINDEX_AGE_DAYS;
}
