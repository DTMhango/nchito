/**
 * Portal accounts and sign-in handoffs, typed against the generated contract (`schema.d.ts`).
 * Endpoints: `/api/portal-accounts` (list, create, get, patch, delete, refresh, give-up) and
 * the pending-action get/resolve. No password or secret field exists anywhere here.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type PortalAccount = S["PortalAccountOut"]
export type PortalAccountWrite = S["PortalAccountWrite"]
export type PortalAccountPatch = S["PortalAccountPatch"]
export type PortalAccountStatus = PortalAccount["status"]
export type GiveUpIn = S["GiveUpIn"]
export type GiveUpOut = S["GiveUpOut"]
export type RefreshOut = S["RefreshOut"]
export type ReleaseRecord = S["ReleaseRecord"]
export type PendingAction = S["PendingActionOut"]
export type ResolveIn = S["ResolveIn"]

export const accountKeys = {
  all: ["portal-accounts"] as const,
  list: (status: PortalAccountStatus | null) =>
    ["portal-accounts", "list", status ?? "all"] as const,
  action: (id: string) => ["pending-actions", "one", id] as const,
  releases: (applicationId: string) =>
    ["applications", "releases", applicationId] as const,
}

export const accountsQuery = (status: PortalAccountStatus | null = null) =>
  queryOptions({
    queryKey: accountKeys.list(status),
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/portal-accounts", {
            params: { query: status ? { status } : {} },
          })
        )
      ).items,
  })

export const createAccount = (body: PortalAccountWrite) =>
  unwrap(api.POST("/api/portal-accounts", { body }))
export const updateAccount = (id: string, body: PortalAccountPatch) =>
  unwrap(
    api.PATCH("/api/portal-accounts/{account_id}", {
      params: { path: { account_id: id } },
      body,
    })
  )
export const deleteAccount = (id: string) =>
  unwrap(
    api.DELETE("/api/portal-accounts/{account_id}", {
      params: { path: { account_id: id } },
    })
  )
export const refreshAccounts = () =>
  unwrap(api.POST("/api/portal-accounts/refresh"))

/** "Apply myself instead" (`manual_handoff`) or "Skip" (`skipped`) for a sign-in style blocker. */
export const giveUp = (actionId: string, body: GiveUpIn) =>
  unwrap(
    api.POST("/api/portal-accounts/actions/{action_id}/give-up", {
      params: { path: { action_id: actionId } },
      body,
    })
  )

export const pendingActionQuery = (id: string) =>
  queryOptions({
    queryKey: accountKeys.action(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/pending-actions/{action_id}", {
          params: { path: { action_id: id } },
        })
      ),
  })

export const resolvePendingAction = (id: string, body: ResolveIn) =>
  unwrap(
    api.POST("/api/pending-actions/{action_id}/resolve", {
      params: { path: { action_id: id } },
      body,
    })
  )

/** What the runner was given (`get_packet`) and what it entered (last permit request), per task. */
export const releasesQuery = (applicationId: string) =>
  queryOptions({
    queryKey: accountKeys.releases(applicationId),
    queryFn: () =>
      unwrap(
        api.GET("/api/applications/{application_id}/releases", {
          params: { path: { application_id: applicationId } },
        })
      ),
  })
