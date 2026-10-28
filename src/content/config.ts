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
    cover_image: z.string().optional(),
    cover_credit: z.string().optional(),
    generato_il: z.string().optional()
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

const guide = defineCollection({
  type: 'content',
  schema: z.object({
    titolo: z.string(),
    descrizione: z.string(),
    sommario: z.string(),
    ordine: z.number().default(100),
    aggiornato: z.string().optional(),
    pubblicato: z.boolean().default(true),
  }),
});

export const collections = {
  articoli,
  'giocatori-profilo': giocatoriProfilo,
  'tornei-profilo': torneiProfilo,
  guide,
};
