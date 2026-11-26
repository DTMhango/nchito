/**
 * Portal accounts and runner activity. These endpoints have no generated types yet (see
 * w3-pending-types.ts), so this file uses a small fetch helper that raises the same ApiError
 * as the typed client. Pending-action calls use the typed client.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, ApiError, unwrap } from "@/lib/api/client"
import type { PendingAction } from "@/features/applications/api"
import type {
  PortalAccount,
  PortalAccountIn,
  RunnerCaps,
  RunnerTask,
} from "./w3-pending-types"

async function call<T>(
  method: "GET" | "POST" | "PUT",
  path: string,
  body?: unknown
): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "include",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  const data: unknown = text ? JSON.parse(text) : undefined
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

export const accountKeys = {
  all: ["portal-accounts"] as const,
  action: (id: string) => ["pending-actions", "one", id] as const,
  tasks: (tokenId: string) => ["runners", tokenId, "tasks"] as const,
  caps: (tokenId: string) => ["runners", tokenId, "caps"] as const,
}

export const accountsQuery = () =>
  queryOptions({
    queryKey: accountKeys.all,
    queryFn: () => call<PortalAccount[]>("GET", "/api/portal-accounts"),
  })
export const saveAccount = (id: string | null, body: PortalAccountIn) =>
  id
    ? call<PortalAccount>("PUT", `/api/portal-accounts/${id}`, body)
    : call<PortalAccount>("POST", "/api/portal-accounts", body)

export const pendingActionQuery = (id: string) =>
  queryOptions({
    queryKey: accountKeys.action(id),
    queryFn: (): Promise<PendingAction> =>
      unwrap(
        api.GET("/api/pending-actions/{action_id}", {
          params: { path: { action_id: id } },
        })
      ),
  })

export const runnerTasksQuery = (tokenId: string, enabled = true) =>
  queryOptions({
    queryKey: accountKeys.tasks(tokenId),
    queryFn: () => call<RunnerTask[]>("GET", `/api/runners/${tokenId}/tasks`),
    enabled,
  })
export const runnerCapsQuery = (tokenId: string) =>
  queryOptions({
    queryKey: accountKeys.caps(tokenId),
    queryFn: () => call<RunnerCaps>("GET", `/api/runners/${tokenId}/caps`),
  })
export const saveRunnerCaps = (tokenId: string, body: RunnerCaps) =>
  call<RunnerCaps>("PUT", `/api/runners/${tokenId}/caps`, body)
