// Google News sitemap: articoli pubblicati negli ultimi 48 ore.
// Google richiede che questa sitemap NON contenga articoli piu' vecchi di 2 giorni.
import { getCollection } from 'astro:content';

export async function GET(context) {
  const articoli = await getCollection('articoli', ({ data }) => data.pubblicato !== false && data.noindex !== true);
  const news = await getCollection('news', ({ data }) => data.pubblicato !== false);
  const site = context.site?.toString().replace(/\/$/, '') || 'https://analisitennis.it';

  const now = Date.now();
  const windowMs = 48 * 60 * 60 * 1000;
  const tempo = (x) => (x.data.generato_il ? new Date(x.data.generato_il) : new Date(x.data.data)).valueOf();

  // Articoli-partita e notizie, entrambi nella finestra 48h di Google News.
  const entries = [
    ...articoli.map(a => ({ loc: `/articoli/${a.slug}`, t: tempo(a), titolo: a.data.titolo })),
    ...news.map(n => ({ loc: `/news/${n.slug}`, t: tempo(n), titolo: n.data.titolo })),
  ].filter(e => now - e.t <= windowMs).sort((a, b) => b.t - a.t);

  const items = entries.map(e => {
    const dt = new Date(e.t).toISOString();
    const esc = s => (s || '').replace(/[<>&"']/g, c => ({ '<':'&lt;', '>':'&gt;', '&':'&amp;', '"':'&quot;', "'":'&apos;' }[c]));
    return `  <url>
    <loc>${site}${e.loc}</loc>
    <news:news>
      <news:publication>
        <news:name>AnalisiTennis</news:name>
        <news:language>it</news:language>
      </news:publication>
      <news:publication_date>${dt}</news:publication_date>
      <news:title>${esc(e.titolo)}</news:title>
    </news:news>
  </url>`;
  }).join('\n');

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
${items}
</urlset>`;

  return new Response(xml, { headers: { 'Content-Type': 'application/xml' } });
}
