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
    cover_credit: z.string().optional()
  })
});

export const collections = { articoli };
