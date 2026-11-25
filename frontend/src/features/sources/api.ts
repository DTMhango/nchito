/**
 * Sources, watched employers, schedules and runs: typed against the generated OpenAPI
 * types (`schema.d.ts`), with TanStack Query keys and options. Kept inside this feature so
 * it does not disturb the wave 0 hand-written contract.
 */
import createClient from "openapi-fetch"
import { queryOptions } from "@tanstack/react-query"
import { unwrap } from "@/lib/api/client"
import type { components, paths } from "@/lib/api/schema.d"

export type Source = components["schemas"]["SourceOut"]
export type SourceInput = components["schemas"]["SourceIn"]
export type SourceTest = components["schemas"]["SourceTestOut"]
export type Employer = components["schemas"]["WatchedEmployerOut"]
export type EmployerInput = components["schemas"]["WatchedEmployerIn"]
export type Detected = components["schemas"]["DetectOut"]
export type Schedule = components["schemas"]["ScheduleOut"]
export type ScheduleInput = components["schemas"]["ScheduleIn"]
export type RunBase = components["schemas"]["RunOut"]
export type RunCreate = components["schemas"]["RunCreate"]
export type RunKind = RunBase["kind"]
export type RunStatus = RunBase["status"]
export type SourceRunResult = components["schemas"]["SourceRunResult"]

/** What a dry run would have done. Not in the contract yet; the UI reads it when present. */
export type ProposedAction = { kind: string; summary: string; job?: string }
export type Run = RunBase & { proposed_actions?: ProposedAction[] }

const origin =
  typeof window !== "undefined" ? window.location.origin : "http://localhost"
const gen = createClient<paths>({
  baseUrl: origin,
  credentials: "include",
  fetch: (request: Request) => globalThis.fetch(request),
})

export const sourceKeys = {
  sources: ["sources"] as const,
  employers: ["watched-employers"] as const,
  schedules: ["schedules"] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["runs", id] as const,
}

const noContent = async (
  call: Promise<{ response: Response; error?: unknown }>
) => {
  await unwrap(
    call as Promise<{ data?: undefined; error?: unknown; response: Response }>
  )
}

// ---- sources ----
export const listSources = async () =>
  (await unwrap(gen.GET("/api/sources", { params: { query: { limit: 200 } } })))
    .items
export const updateSource = (id: string, body: SourceInput) =>
  unwrap(
    gen.PUT("/api/sources/{item_id}", {
      params: { path: { item_id: id } },
      body,
    })
  )
export const testSource = (id: string) =>
  unwrap(
    gen.POST("/api/sources/{item_id}/test", {
      params: { path: { item_id: id } },
    })
  )
export const sourcesQuery = () =>
  queryOptions({ queryKey: sourceKeys.sources, queryFn: listSources })

/** Convert a stored source into the input shape (for partial updates). */
export const toSourceInput = (s: Source): SourceInput => ({
  connector: s.connector,
  name: s.name,
  access: s.access,
  config: s.config,
  access_notes: s.access_notes,
  rate_limit: s.rate_limit,
  permitted_actions: s.permitted_actions,
  enabled: s.enabled,
})

// ---- watched employers ----
export const listEmployers = async () =>
  (
    await unwrap(
      gen.GET("/api/watched-employers", { params: { query: { limit: 200 } } })
    )
  ).items
export const createEmployer = (body: EmployerInput) =>
  noContent(gen.POST("/api/watched-employers", { body }))
export const updateEmployer = (id: string, body: EmployerInput) =>
  unwrap(
    gen.PUT("/api/watched-employers/{item_id}", {
      params: { path: { item_id: id } },
      body,
    })
  )
export const deleteEmployer = (id: string) =>
  noContent(
    gen.DELETE("/api/watched-employers/{item_id}", {
      params: { path: { item_id: id } },
    })
  )
export const detectBoard = (url: string) =>
  unwrap(gen.POST("/api/sources/detect", { body: { url } }))
export const employersQuery = () =>
  queryOptions({ queryKey: sourceKeys.employers, queryFn: listEmployers })

export const toEmployerInput = (e: Employer): EmployerInput => ({
  name: e.name,
  board_type: e.board_type,
  board_slug: e.board_slug,
  priority: e.priority,
  cooldown_days: e.cooldown_days,
  always_ask_first: e.always_ask_first,
})

// ---- schedules ----
export const listSchedules = async () =>
  (
    await unwrap(
      gen.GET("/api/schedules", { params: { query: { limit: 100 } } })
    )
  ).items
export const createSchedule = (body: ScheduleInput) =>
  noContent(gen.POST("/api/schedules", { body }))
export const updateSchedule = (id: string, body: ScheduleInput) =>
  unwrap(
    gen.PUT("/api/schedules/{item_id}", {
      params: { path: { item_id: id } },
      body,
    })
  )
export const deleteSchedule = (id: string) =>
  noContent(
    gen.DELETE("/api/schedules/{item_id}", {
      params: { path: { item_id: id } },
    })
  )
export const schedulesQuery = () =>
  queryOptions({ queryKey: sourceKeys.schedules, queryFn: listSchedules })

// ---- runs ----
export const listRuns = async () =>
  (await unwrap(gen.GET("/api/runs", { params: { query: { limit: 100 } } })))
    .items as Run[]
export const getRun = (id: string) =>
  unwrap(
    gen.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } })
  ) as Promise<Run>
export const createRun = (body: RunCreate) =>
  noContent(gen.POST("/api/runs", { body }))
export const cancelRun = (id: string) =>
  unwrap(
    gen.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: id } } })
  )

const active = (s: RunStatus) => s === "running" || s === "queued"
export const isActive = active
export const runsQuery = () =>
  queryOptions({
    queryKey: sourceKeys.runs,
    queryFn: listRuns,
    // Polling is the fallback when the event stream is not connected.
    refetchInterval: (q) =>
      q.state.data?.some((r) => active(r.status)) ? 4000 : false,
  })
export const runQuery = (id: string) =>
  queryOptions({
    queryKey: sourceKeys.run(id),
    queryFn: () => getRun(id),
    refetchInterval: (q) =>
      q.state.data && active(q.state.data.status) ? 3000 : false,
  })

// ---- missed-run policy (one global setting) ----
export type MissedRun = "catch_up_once" | "skip"
const MISSED_KEY = "schedule.missed_run"
export const getMissedRun = async () =>
  (
    await unwrap(
      gen.GET("/api/settings/{key}", { params: { path: { key: MISSED_KEY } } })
    )
  ).value as MissedRun
export const putMissedRun = (value: MissedRun) =>
  unwrap(
    gen.PUT("/api/settings/{key}", {
      params: { path: { key: MISSED_KEY } },
      body: { value, reason: "Changed on the Autopilot schedules screen" },
    })
  )
export const missedRunQuery = () =>
  queryOptions({ queryKey: ["settings", MISSED_KEY], queryFn: getMissedRun })

export const toScheduleInput = (s: Schedule): ScheduleInput => ({
  name: s.name,
  kind: s.kind,
  campaign_id: s.campaign_id,
  cron: s.cron,
  timezone: s.timezone,
  enabled: s.enabled,
  dry_run: s.dry_run,
})
