/** Employers and their chip: typed against the generated contract (CONTRACTS "Wave 4 bulk additions"). */
import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]

export type EmployerRow = S["EmployerRowOut"]
export type EmployerDetail = S["EmployerDetailOut"]
export type EmployerChip = S["ChipOut"]
export type EmployerState = EmployerChip["state"]
export type EmployerPolicy = S["PolicyIn"]
export type EmployerRole = S["RoleOut"]

export const employerKeys = {
  all: ["employers"] as const,
  list: (state: string, q: string) => ["employers", "list", state, q] as const,
  detail: (key: string) => ["employers", "detail", key] as const,
  chips: (ids: string) => ["employers", "chips", ids] as const,
}

export const STATE_LABEL: Record<EmployerState, string> = {
  free: "Free to apply",
  role_in_progress: "Role in progress",
  cooling_down: "Cooling down",
  always_ask_first: "Always ask first",
  blocked: "Never apply",
}

export const employersQuery = (state: string, q: string) =>
  queryOptions({
    queryKey: employerKeys.list(state, q),
    queryFn: () =>
      unwrap(
        api.GET("/api/employers", {
          params: {
            query: {
              state: state ? (state as EmployerState) : undefined,
              q: q.trim() || undefined,
            },
          },
        })
      ),
  })

export const employerQuery = (key: string) =>
  queryOptions({
    queryKey: employerKeys.detail(key),
    queryFn: () =>
      unwrap(api.GET("/api/employers/detail", { params: { query: { key } } })),
  })

export const setPolicy = (key: string, body: EmployerPolicy) =>
  unwrap(
    api.PATCH("/api/employers/policy", { params: { query: { key } }, body })
  )

export const endCooldown = (key: string, reason: string) =>
  unwrap(
    api.POST("/api/employers/end-cooldown", {
      params: { query: { key } },
      body: { reason },
    })
  )

export const mergeEmployer = (key: string, into: string, remember: boolean) =>
  unwrap(
    api.POST("/api/employers/merge", {
      params: { query: { key } },
      body: { into, remember_alias: remember },
    })
  )

export const splitEmployer = (alias: string) =>
  unwrap(api.POST("/api/employers/split", { body: { alias } }))

const chipStates = (job_ids: string[]) =>
  unwrap(api.POST("/api/employers/states", { body: { job_ids } }))

/** The employer chip for each job id (Matches rows, Applications cards, the job page). */
export function useEmployerChips(jobIds: string[]) {
  const ids = [...new Set(jobIds)].sort()
  const q = useQuery({
    queryKey: employerKeys.chips(ids.join(",")),
    queryFn: () => chipStates(ids),
    enabled: ids.length > 0,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
  return q.data?.states ?? EMPTY
}
const EMPTY: Record<string, EmployerChip> = {}
