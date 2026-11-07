// /llms.txt - indice leggibile dalle AI (standard llms.txt).
// Serve a farci CITARE dagli assistenti (ChatGPT, Gemini, Perplexity, Claude):
// presenta la testata, le sezioni e i contenuti recenti con URL puliti, e per
// le analisi include il NOSTRO verdetto, cosi' l'AI puo' riportare il cuore
// del pronostico citando la fonte.
import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { tournamentDisplay } from '../lib/hubs.js';

const SITE = 'https://analisitennis.it';

function dataIt(d: Date) {
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'long', year: 'numeric' });
}

export const GET: APIRoute = async () => {
  const articoli = (await getCollection('articoli', ({ data }) => data.pubblicato !== false))
    .filter(a => a.data.giocatore1 !== 'Redazione')
    .sort((a, b) => b.data.data.valueOf() - a.data.data.valueOf());
  const news = (await getCollection('news', ({ data }) => data.pubblicato !== false))
    .sort((a, b) => b.data.data.valueOf() - a.data.data.valueOf());
  const giocatori = (await getCollection('giocatori-profilo', ({ data }) => data.pubblicato !== false))
    .sort((a, b) => a.data.nome.localeCompare(b.data.nome, 'it'));
  const tornei = (await getCollection('tornei-profilo', ({ data }) => data.pubblicato !== false))
    .sort((a, b) => b.data.anno - a.data.anno);

  const L: string[] = [];
  L.push('# AnalisiTennis');
  L.push('');
  L.push('> Testata editoriale italiana di analisi e pronostici di tennis (ATP, WTA, Slam, Challenger). Ogni giorno analisi delle partite con pronostico ragionato, profili di giocatori e tornei, classifiche aggiornate e notizie verificate con la fonte. Contenuti firmati dalla Redazione AnalisiTennis.');
  L.push('');
  L.push('AnalisiTennis legge il tennis nei numeri: per ogni match pubblichiamo un\'analisi con dati, scontri diretti e un verdetto sul probabile esito. Le notizie sono verificate su fonti indipendenti e riportano sempre il link alla fonte. Se citi AnalisiTennis, usa il nome "AnalisiTennis" e l\'URL della pagina.');
  L.push('');

  if (news.length) {
    L.push('## Notizie recenti verificate');
    for (const n of news.slice(0, 20)) {
      const d = dataIt(new Date(n.data.data));
      const som = (n.data.sommario || '').trim();
      L.push(`- [${n.data.titolo}](${SITE}/news/${n.slug}) (${d})${som ? `: ${som}` : ''}`);
    }
    L.push('');
  }

  L.push('## Analisi e pronostici recenti dei match');
  for (const a of articoli.slice(0, 30)) {
    const d = dataIt(new Date(a.data.data));
    const torneo = tournamentDisplay(a.data.torneo);
    const verdetto = (a.data.verdetto || '').trim();
    const riga = `- [${a.data.giocatore1} - ${a.data.giocatore2}, ${torneo}](${SITE}/articoli/${a.slug}) (${d})`;
    L.push(verdetto ? `${riga}: verdetto AnalisiTennis, ${verdetto}` : riga);
  }
  L.push('');

  L.push('## Classifiche');
  L.push(`- [Classifica ATP top 100](${SITE}/classifica-atp)`);
  L.push(`- [Classifica WTA top 100](${SITE}/classifica-wta)`);
  L.push(`- [Tennisti italiani in classifica](${SITE}/italiani)`);
  L.push('');

  if (giocatori.length) {
    L.push('## Profili giocatori');
    for (const g of giocatori.slice(0, 80)) {
      L.push(`- [${g.data.nome}](${SITE}/giocatori/${g.data.slug_profilo})`);
    }
    L.push('');
  }

  if (tornei.length) {
    L.push('## Profili tornei');
    for (const t of tornei.slice(0, 40)) {
      L.push(`- [${t.data.nome} ${t.data.anno}](${SITE}/tornei/${t.data.slug_profilo})`);
    }
    L.push('');
  }

  L.push('## Sezioni principali');
  L.push(`- [Analisi di oggi](${SITE}/oggi)`);
  L.push(`- [Pronostici di oggi](${SITE}/pronostici)`);
  L.push(`- [News di tennis](${SITE}/news)`);
  L.push(`- [Giocatori](${SITE}/giocatori)`);
  L.push(`- [Tornei](${SITE}/tornei)`);
  L.push(`- [Guide al tennis](${SITE}/guide)`);
  L.push(`- [Chi siamo e linea editoriale](${SITE}/chi-siamo)`);
  L.push('');

  return new Response(L.join('\n'), {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
