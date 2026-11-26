/**
 * Studio calls, typed against the generated contract (`schema.d.ts`). Components import from
 * here, never from openapi-fetch. Kit lists (facts, guardrails, templates, answers) come
 * through the Kit's own query options so both screens share one cache.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"

export type ApplicationDetail = Schemas["ApplicationDetail"]
export type ApplicationSummary = Schemas["ApplicationSummary"]
export type Spec = Schemas["ApplicationSpec-Output"]
export type SpecInput = Schemas["ApplicationSpec-Input"]
export type SpecItem = Schemas["SpecItem"]
export type SpecExperience = Schemas["SpecExperience"]
export type SpecState = Schemas["SpecStateOut"]
export type DraftAnswer = Schemas["DraftAnswer"]
export type RequirementMatch = Schemas["RequirementMatch"]
export type CheckResult = Schemas["CheckResult"]
export type JobDetail = Schemas["JobDetail"]
export type Requirement = Schemas["Requirement"]
export type RunOut = Schemas["RunOut"]
export type PacketOut = Schemas["PacketOut"]
export type PacketBuildIn = Schemas["PacketBuildIn"]
export type PacketBuildOut = Schemas["PacketBuildOut"]
export type PacketFile = Schemas["PacketFile"]
export type PendingAction = Schemas["PendingActionOut"]
export type FactOut = Schemas["FactOut"]
export type FactIn = Schemas["FactIn"]
export type GuardrailOut = Schemas["GuardrailOut"]
export type TemplateOut = Schemas["TemplateOut"]
export type ExperienceOut = Schemas["ExperienceOut"]
export type DocumentOut = Schemas["DocumentOut"]
export type RenderIn = Schemas["RenderIn"]
export type RenderOut = Schemas["RenderOut"]
export type RenderWarning = Schemas["RenderWarning"]
export type TailoringStatus = NonNullable<SpecState["tailoring"]>
export type DocKind = "cv" | "letter" | "answers"
export type RenderKind = RenderIn["kind"]
export type DocFormat = DocumentOut["fmt"]

export const studioKeys = {
  all: ["studio"] as const,
  application: (id: string) => ["studio", "application", id] as const,
  /** Under the application key, so refreshing the application refreshes its spec state. */
  spec: (id: string) => ["studio", "application", id, "spec"] as const,
  render: (id: string, kind: RenderKind, template: string, hash: string) =>
    ["studio", "application", id, "render", kind, template, hash] as const,
  job: (id: string) => ["studio", "job", id] as const,
  run: (id: string) => ["studio", "run", id] as const,
  pending: ["studio", "pending-actions"] as const,
  picker: ["studio", "picker"] as const,
}

const path = (id: string) => ({ params: { path: { application_id: id } } })

export const applicationQuery = (id: string) =>
  queryOptions({
    queryKey: studioKeys.application(id),
    queryFn: () =>
      unwrap(api.GET("/api/applications/{application_id}", path(id))),
    retry: false,
  })

/** Tailoring states that are still working: the spec state is polled while one is open. */
export const OPEN_TAILORING = new Set<TailoringStatus>(["queued", "running"])

/** The latest spec version, whether its checks still hold, its answers and its tailoring. */
export const specQuery = (id: string, pollMs: number) =>
  queryOptions({
    queryKey: studioKeys.spec(id),
    queryFn: () =>
      unwrap(api.GET("/api/applications/{application_id}/spec", path(id))),
    retry: false,
    refetchInterval: (q) =>
      q.state.data?.tailoring && OPEN_TAILORING.has(q.state.data.tailoring)
        ? pollMs
        : false,
  })

export const jobQuery = (id: string | undefined) =>
  queryOptions({
    queryKey: studioKeys.job(id ?? "none"),
    enabled: !!id,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id! } } })
      ),
  })

/** Applications that can be opened in the Studio (drafting or waiting for approval). */
export const STUDIO_STAGES: ApplicationSummary["stage"][] = [
  "shortlisted",
  "tailoring",
  "ready",
]
export const pickerQuery = () =>
  queryOptions({
    queryKey: studioKeys.picker,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/applications", {
            params: { query: { limit: 200, hide_snoozed: true } },
          })
        )
      ).items.filter((a) => STUDIO_STAGES.includes(a.stage)),
  })

/** A tailoring run, when the server names one (for its cost). */
export const ACTIVE_RUN = new Set<RunOut["status"]>(["queued", "running"])
export const runQuery = (id: string | undefined, pollMs: number) =>
  queryOptions({
    queryKey: studioKeys.run(id ?? "none"),
    enabled: !!id,
    queryFn: () =>
      unwrap(
        api.GET("/api/runs/{run_id}", { params: { path: { run_id: id! } } })
      ),
    refetchInterval: (q) =>
      q.state.data && ACTIVE_RUN.has(q.state.data.status) ? pollMs : false,
  })

export const pendingQuery = () =>
  queryOptions({
    queryKey: studioKeys.pending,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/pending-actions", {
            params: { query: { status: "open" } },
          })
        )
      ).items,
  })

/** 202: queues tailoring, or returns the request already open (idempotent). */
export const startTailoring = (id: string) =>
  unwrap(api.POST("/api/applications/{application_id}/tailor", path(id)))

/** Stores an owner version and runs the code checks (409 once the application has gone out). */
export const saveSpec = (id: string, spec: SpecInput) =>
  unwrap(
    api.PUT("/api/applications/{application_id}/spec", {
      ...path(id),
      body: { spec },
    })
  )

/** Re-runs every check on the latest version (409 when there is no draft). */
export const runChecks = (id: string) =>
  unwrap(api.POST("/api/applications/{application_id}/check", path(id)))

export const waiveOnce = (
  guardrailId: string,
  applicationId: string,
  reason: string
) =>
  unwrap(
    api.POST("/api/kit/guardrails/{item_id}/waivers", {
      params: { path: { item_id: guardrailId } },
      body: { application_id: applicationId, reason },
    })
  )

/** Renders (or returns the stored) files for the current spec; warnings come from the renderer. */
export const renderDocuments = (id: string, body: RenderIn) =>
  unwrap(
    api.POST("/api/applications/{application_id}/documents/render", {
      ...path(id),
      body,
    })
  )

/** The layout warnings for one document and template, for the saved spec version `hash`. */
export const renderQuery = (
  id: string,
  kind: RenderKind,
  template: string,
  hash: string | null
) =>
  queryOptions({
    queryKey: studioKeys.render(id, kind, template, hash ?? "none"),
    enabled: !!hash,
    retry: false,
    staleTime: Infinity,
    queryFn: () =>
      renderDocuments(id, { kind, template_key: template, formats: ["pdf"] }),
  })

/** Snapshot what would be sent; the approval policy runs on it. */
export const buildPacket = (id: string, body: PacketBuildIn) =>
  unwrap(
    api.POST("/api/applications/{application_id}/packet", {
      ...path(id),
      body,
    })
  )

export const mailConnectionsQuery = () =>
  queryOptions({
    queryKey: ["studio", "connections"] as const,
    queryFn: () => unwrap(api.GET("/api/connections")),
    retry: false,
  })

export const createDraftFact = (body: FactIn) =>
  unwrap(api.POST("/api/kit/facts", { body }))

/** The rendered file. A plain link, so the browser downloads it with the session cookie. */
export function documentUrl(
  id: string,
  kind: DocKind,
  fmt: DocFormat,
  template?: string
) {
  const q = new URLSearchParams({ fmt })
  if (template && kind !== "answers") q.set("template", template)
  return `/api/applications/${encodeURIComponent(id)}/documents/${kind}?${q}`
}
