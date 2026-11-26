/**
 * Kit API layer: typed against the generated `/api/kit/*` contract (docs/openapi.json).
 * Feature code imports from here. Query keys are per resource; every write invalidates its
 * list and the review count.
 */
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { api, toFormData, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type ExperienceOut = S["ExperienceOut"]
export type ExperienceIn = S["ExperienceIn"]
export type FactOut = S["FactOut"]
export type FactIn = S["FactIn"]
export type SkillOut = S["SkillOut"]
export type SkillIn = S["SkillIn"]
export type SkillAliasOut = S["SkillAliasOut"]
export type ReferenceOut = S["ReferenceOut"]
export type ReferenceIn = S["ReferenceIn"]
export type TrackOut = S["TrackOut"]
export type TrackIn = S["TrackIn"]
export type GuardrailOut = S["GuardrailOut"]
export type GuardrailIn = S["GuardrailIn"]
export type GuardrailCheckOut = S["GuardrailCheckOut"]
export type AnswerOut = S["AnswerOut"]
export type AnswerIn = S["app__api__routers__kit__AnswerIn"]
export type TemplateOut = S["TemplateOut"]
export type VaultDocumentOut = Omit<S["VaultDocumentOut"], "doc_type"> & {
  doc_type: VaultDocumentUpdate["doc_type"]
}
export type VaultDocumentUpdate = S["VaultDocumentUpdate"]
export type ReviewItem = S["ReviewItem"]
export type ReviewEntity = ReviewItem["entity"]
export type FactKind = FactOut["kind"]
export type GuardrailScope = NonNullable<GuardrailIn["scope"]>[number]

/** Every kit resource that has the plain list / create / update / delete shape. */
export type Resource =
  | "experiences"
  | "facts"
  | "skills"
  | "references"
  | "tracks"
  | "guardrails"
  | "answers"
  | "templates"
  | "vault"
  | "skill-aliases"

// The Kit CRUD paths are one family of identical shapes addressed by a resource name; one
// loosely typed view of the shared client keeps that family short. Public functions below
// carry the real types, and the one-off endpoints use the typed client.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const raw = api as any

const base = (r: Resource) =>
  r === "skill-aliases" ? "/api/skill-aliases" : `/api/kit/${r}`

type Page<T> = {
  items: T[]
  total?: number | null
  next_cursor?: string | null
}

/** Fetch every page of a list (the Kit is small; one owner, hundreds of rows at most). */
async function listAll<T>(
  r: Resource,
  query: Record<string, string | undefined> = {}
): Promise<T[]> {
  const out: T[] = []
  let cursor: string | undefined
  for (let i = 0; i < 20; i++) {
    const page = await unwrap<Page<T>>(
      raw.GET(base(r), { params: { query: { ...query, limit: 200, cursor } } })
    )
    out.push(...page.items)
    if (!page.next_cursor) break
    cursor = page.next_cursor
  }
  return out
}

export const kitKeys = {
  all: ["kit"] as const,
  list: (r: Resource) => ["kit", r] as const,
  review: ["kit", "review"] as const,
}

export const listQuery = <T>(r: Resource) =>
  queryOptions<T[]>({
    queryKey: kitKeys.list(r),
    queryFn: () => listAll<T>(r),
    staleTime: 15_000,
  })

export const reviewQuery = () =>
  queryOptions<ReviewItem[]>({
    queryKey: kitKeys.review,
    queryFn: async () => {
      const page = await unwrap(api.GET("/api/kit/review"))
      return page.items
    },
    staleTime: 15_000,
  })

export const useKitList = <T>(r: Resource) => useQuery(listQuery<T>(r))
export const useReview = () => useQuery(reviewQuery())

type SaveArgs<In> = { id?: string; body: In }

/** Create (no id) or update (id). Invalidates the list and the review count. */
export function useSave<Out, In>(r: Resource) {
  const qc = useQueryClient()
  return useMutation<Out, Error, SaveArgs<In>>({
    mutationFn: ({ id, body }) =>
      id
        ? unwrap(
            raw.PUT(`${base(r)}/{item_id}`, {
              params: { path: { item_id: id } },
              body,
            })
          )
        : unwrap(raw.POST(base(r), { body })),
    // Returned so callers using mutateAsync resolve after the list has refetched.
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: kitKeys.list(r) }),
        qc.invalidateQueries({ queryKey: kitKeys.review }),
      ]),
  })
}

export function useRemove(r: Resource) {
  const qc = useQueryClient()
  return useMutation<unknown, Error, string>({
    mutationFn: (id) =>
      unwrap(
        raw.DELETE(`${base(r)}/{item_id}`, {
          params: { path: { item_id: id } },
        })
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: kitKeys.list(r) })
      void qc.invalidateQueries({ queryKey: kitKeys.review })
    },
  })
}

/** Approve or retire a fact. */
export function useFactAction() {
  const qc = useQueryClient()
  return useMutation<
    FactOut,
    Error,
    { id: string; action: "approve" | "retire" }
  >({
    mutationFn: ({ id, action }) =>
      unwrap(
        action === "approve"
          ? api.POST("/api/kit/facts/{item_id}/approve", {
              params: { path: { item_id: id } },
            })
          : api.POST("/api/kit/facts/{item_id}/retire", {
              params: { path: { item_id: id } },
            })
      ),
    onSuccess: () =>
      void qc.invalidateQueries({ queryKey: kitKeys.list("facts") }),
  })
}

/** Confirm or drop an item waiting in "Needs review". */
export function useReviewDecision() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    Error,
    { entity: ReviewEntity; id: string; decision: "confirm" | "drop" }
  >({
    mutationFn: ({ entity, id, decision }) =>
      unwrap(
        api.POST("/api/kit/review/{entity}/{item_id}", {
          params: { path: { entity, item_id: id } },
          body: { decision },
        })
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: kitKeys.all }),
  })
}

export function useGuardrailCheck() {
  return useMutation<
    GuardrailCheckOut,
    Error,
    { texts: Partial<Record<GuardrailScope, string>>; file_names?: string[] }
  >({
    mutationFn: (body) =>
      unwrap(api.POST("/api/kit/guardrails/check", { body })),
  })
}

export function useUploadDocument() {
  const qc = useQueryClient()
  return useMutation<
    VaultDocumentOut,
    Error,
    {
      file: File
      title: string
      doc_type: VaultDocumentOut["doc_type"]
      sensitivity: VaultDocumentOut["sensitivity"]
    }
  >({
    mutationFn: (v) =>
      unwrap(
        api.POST("/api/kit/vault", {
          // Multipart: the generated body types the file as a string; the File goes as is.
          body: {
            file: v.file as unknown as string,
            title: v.title,
            doc_type: v.doc_type,
            sensitivity: v.sensitivity,
          },
          bodySerializer: toFormData,
        })
        // The contract types doc_type as a plain string; it is one of the upload's choices.
      ) as Promise<VaultDocumentOut>,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: kitKeys.list("vault") })
      void qc.invalidateQueries({ queryKey: kitKeys.review })
    },
  })
}

export const vaultDownloadUrl = (id: string) => `/api/kit/vault/${id}/download`

/** Which Kit page an item waiting for review lives on. */
export const REVIEW_PAGE: Partial<Record<ReviewEntity, string>> = {
  person: "library",
  experience: "library",
  fact: "library",
  skill: "library",
  reference: "library",
  track: "tracks",
  guardrail: "guardrails",
  answer: "answers",
  vault_document: "documents",
  template: "templates",
}
