import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';

export async function GET(context) {
  const articoli = await getCollection('articoli', ({ data }) => data.pubblicato !== false);
  return rss({
    title: 'AnalisiTennis',
    description: 'Il tennis letto nei numeri. Analisi autoriali quotidiane sulle partite di tennis ATP, WTA e Challenger.',
    site: context.site,
    items: articoli.map(a => ({
      title: a.data.titolo,
      description: a.data.descrizione,
      pubDate: a.data.data,
      link: `/articoli/${a.slug}`,
      author: a.data.autore,
      categories: [a.data.categoria, a.data.torneo]
    })),
    customData: `<language>it-IT</language>`
  });
}
