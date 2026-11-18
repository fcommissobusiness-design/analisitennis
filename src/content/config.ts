import { defineCollection, z } from 'astro:content';

const articoli = defineCollection({
  type: 'content',
  schema: z.object({
    titolo: z.string(),
    sottotitolo: z.string(),
    data: z.coerce.date(),
    autore: z.string().default('Redazione AnalisiTennis'),
    torneo: z.string(),
    categoria: z.enum(['ATP', 'WTA', 'Challenger', 'ITF', 'Slam', 'Masters']),
    superficie: z.enum(['cemento', 'terra', 'erba', 'indoor']),
    giocatore1: z.string(),
    giocatore2: z.string(),
    tag: z.array(z.string()).default([]),
    verdetto: z.string(),
    descrizione: z.string(),
    pubblicato: z.boolean().default(true),
    // noindex: pagina pubblicata ma esclusa da Google (meta robots noindex +
    // fuori sitemap). Usata per i match minori che Google scansiona ma non
    // indicizza, per non appesantire la qualita' percepita del sito.
    noindex: z.boolean().optional(),
    cover_image: z.string().optional(),
    cover_credit: z.string().optional(),
    cover_file: z.string().optional(),
    cover_focus: z.number().optional(),
    generato_il: z.string().optional(),
    probabilita_favorito: z.string().optional(),
    probabilita_percent: z.number().optional()
  })
});

const giocatoriProfilo = defineCollection({
  type: 'content',
  schema: z.object({
    nome: z.string(),
    slug_profilo: z.string(),
    nazionalita: z.string().optional(),
    data_nascita: z.string().optional(),
    mano: z.string().optional(),
    rovescio: z.string().optional(),
    stile_gioco: z.string().optional(),
    titoli: z.string().optional(),
    altezza: z.string().optional(),
    categoria: z.enum(['ATP', 'WTA', 'Challenger', 'ITF', 'Slam', 'Masters']).optional(),
    superficie_preferita: z.enum(['cemento', 'terra', 'erba', 'indoor']).optional(),
    intro: z.string(),
    cover_image: z.string().optional(),
    cover_credit: z.string().optional(),
    descrizione: z.string(),
    tag: z.array(z.string()).default([]),
    pubblicato: z.boolean().default(true),
    generato_il: z.string().optional()
  })
});

const torneiProfilo = defineCollection({
  type: 'content',
  schema: z.object({
    nome: z.string(),
    slug_profilo: z.string(),
    anno: z.number(),
    citta: z.string().optional(),
    paese: z.string().optional(),
    categoria: z.enum(['ATP', 'WTA', 'Challenger', 'ITF', 'Slam', 'Masters']).optional(),
    superficie: z.enum(['cemento', 'terra', 'erba', 'indoor']).optional(),
    fondato: z.string().optional(),
    intro: z.string(),
    cover_image: z.string().optional(),
    cover_credit: z.string().optional(),
    descrizione: z.string(),
    tag: z.array(z.string()).default([]),
    pubblicato: z.boolean().default(true),
    generato_il: z.string().optional()
  })
});

// Hub torneo pluriennale: pagina pilastro sul torneo nella sua storia
// (senza anno). Es. /tornei/wimbledon, /tornei/roland-garros. Il hub
// raccoglie storia, albo d'oro pluriennale, record e linka ai profili
// anno singolo gia' esistenti (vedi tornei-profilo).
// Collezione separata dai profili anno: schema distinto, nessuna
// collisione d'URL perche' lo slug del hub non contiene l'anno.
const torneiHub = defineCollection({
  type: 'content',
  schema: z.object({
    nome: z.string(),
    slug_profilo: z.string(),
    citta: z.string().optional(),
    paese: z.string().optional(),
    categoria: z.enum(['ATP', 'WTA', 'Challenger', 'ITF', 'Slam', 'Masters']).optional(),
    superficie: z.enum(['cemento', 'terra', 'erba', 'indoor']).optional(),
    fondato: z.string().optional(),
    sede: z.string().optional(),
    // Nome del recordman di titoli in singolare + numero titoli. Dato
    // factual verificato: va riempito solo se certo.
    record_titoli_m: z.string().optional(),
    record_titoli_f: z.string().optional(),
    intro: z.string(),
    cover_image: z.string().optional(),
    cover_credit: z.string().optional(),
    descrizione: z.string(),
    // FAQ 4-6 Q&A, tutte dai dati verificati nel markdown. Generano
    // JSON-LD FAQPage.
    faq: z.array(z.object({
      q: z.string(),
      a: z.string(),
    })).optional(),
    tag: z.array(z.string()).default([]),
    pubblicato: z.boolean().default(true),
    generato_il: z.string().optional()
  })
});

const news = defineCollection({
  type: 'content',
  schema: z.object({
    titolo: z.string(),
    sommario: z.string().default(''),
    data: z.coerce.date(),
    autore: z.string().default('Redazione AnalisiTennis'),
    categoria: z.string(),
    chiave: z.string().optional(),
    fonte_nome: z.string().optional(),
    fonte_url: z.string().optional(),
    tag: z.array(z.string()).default([]),
    generato_il: z.string().optional(),
    pubblicato: z.boolean().default(true),
  }),
});

const guide = defineCollection({
  type: 'content',
  schema: z.object({
    titolo: z.string(),
    descrizione: z.string(),
    sommario: z.string(),
    ordine: z.number().default(100),
    aggiornato: z.string().optional(),
    pubblicato: z.boolean().default(true),
    // FAQ opzionale: 4-6 Q&A didattiche. Se presenti, la pagina aggiunge
    // JSON-LD FAQPage e mostra un blocco "Domande frequenti" a fondo guida.
    faq: z.array(z.object({
      q: z.string(),
      a: z.string(),
    })).optional(),
  }),
});

export const collections = {
  articoli,
  'giocatori-profilo': giocatoriProfilo,
  'tornei-profilo': torneiProfilo,
  'tornei-hub': torneiHub,
  news,
  guide,
};
