import { z } from "zod"

/** `/studio?application=<id>&run=<id>`: the application open, and its tailoring run if live. */
export const studioSearchSchema = z.object({
  application: z.string().optional().catch(undefined),
  run: z.string().optional().catch(undefined),
})
export type StudioSearch = z.infer<typeof studioSearchSchema>
