// Google News sitemap: articoli pubblicati negli ultimi 48 ore.
// Google richiede che questa sitemap NON contenga articoli piu' vecchi di 2 giorni.
import { getCollection } from 'astro:content';

export async function GET(context) {
  const articoli = await getCollection('articoli', ({ data }) => data.pubblicato !== false);
  const site = context.site?.toString().replace(/\/$/, '') || 'https://analisitennis.it';

  const now = Date.now();
  const windowMs = 48 * 60 * 60 * 1000;
  const recenti = articoli.filter(a => {
    const t = (a.data.generato_il ? new Date(a.data.generato_il) : a.data.data).valueOf();
    return now - t <= windowMs;
  });

  recenti.sort((a, b) => {
    const ta = (a.data.generato_il ? new Date(a.data.generato_il) : a.data.data).valueOf();
    const tb = (b.data.generato_il ? new Date(b.data.generato_il) : b.data.data).valueOf();
    return tb - ta;
  });

  const items = recenti.map(a => {
    const dt = (a.data.generato_il ? new Date(a.data.generato_il) : a.data.data).toISOString();
    const esc = s => (s || '').replace(/[<>&"']/g, c => ({ '<':'&lt;', '>':'&gt;', '&':'&amp;', '"':'&quot;', "'":'&apos;' }[c]));
    return `  <url>
    <loc>${site}/articoli/${a.slug}</loc>
    <news:news>
      <news:publication>
        <news:name>AnalisiTennis</news:name>
        <news:language>it</news:language>
      </news:publication>
      <news:publication_date>${dt}</news:publication_date>
      <news:title>${esc(a.data.titolo)}</news:title>
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
