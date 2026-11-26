/**
 * Autopilot, approvals, dispatch, handoff, pending actions and trusted sites: typed against
 * the generated contract. Components import from here, never from openapi-fetch.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, isApiError, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"
import { explainError } from "@/lib/api/refusals"
import { resolveAction } from "@/features/applications/api"

export type PacketOut = Schemas["PacketOut"]
export type DispatchCreateOut = Schemas["DispatchCreateOut"]
export type ReconcileIn = Schemas["ReconcileIn"]
export type ReconcileOut = Schemas["ReconcileOut"]
export type RestoreStateOut = Schemas["RestoreStateOut"]
export type AutopilotState = Schemas["AutopilotState"]
export type TimelineEvent = Schemas["TimelineEvent"]
export type PacketContents = Schemas["PacketContents"]
export type ReceiptOut = Schemas["ReceiptOut"]
export type PacketChange = Schemas["PacketChange"]
export type GateResult = Schemas["GateResult"]
export type DispatchOut = Schemas["DispatchOut"]
export type ManualHandoffOut = Schemas["ManualHandoffOut"]
export type PendingAction = Schemas["PendingActionOut"]
export type ResolveIn = Schemas["ResolveIn"]
export type TrustedSiteOut = Schemas["TrustedSiteOut"]
export type RunnerStatus = Schemas["RunnerStatus"]
export type CampaignOut = Schemas["CampaignOut"]
export type AutomationPolicy = Schemas["AutomationPolicy"]
export type ApplicationSummary = Schemas["ApplicationSummary"]
export type JobSummary = Schemas["JobSummary"]
export type SettingOut = Schemas["SettingOut"]
export type Channel = NonNullable<ApplicationSummary["channel"]>
export type AutomationMode = AutomationPolicy["mode"] & string

export const apKeys = {
  campaigns: ["autopilot", "campaigns"] as const,
  settings: ["autopilot", "settings"] as const,
  runners: ["autopilot", "runners"] as const,
  queue: ["autopilot", "approval-queue"] as const,
  receipt: (id: string) => ["autopilot", "receipt", id] as const,
  packets: (id: string) => ["autopilot", "packets", id] as const,
  handoff: (id: string) => ["autopilot", "handoff", id] as const,
  dispatches: (id: string) => ["autopilot", "dispatches", id] as const,
  packet: (id: string) => ["autopilot", "packet", id] as const,
  timeline: (id: string) => ["autopilot", "timeline", id] as const,
  dispatchApps: ["autopilot", "dispatch-apps"] as const,
  held: ["autopilot", "held-roles"] as const,
  restore: ["autopilot", "restore"] as const,
  // Under "pending-actions" so the wave 1 invalidations (Today, live updates) refresh it too.
  pending: ["pending-actions", "autopilot"] as const,
  trusted: ["autopilot", "trusted-sites"] as const,
}

/** A structured 409 from the apply layer: `{code, reason, gates?, outstanding?}`. */
export { refusalOf, type Refusal } from "@/lib/api/refusals"

/** Plain words for any error: a coded refusal in the app's words, else the error's message. */
export const errorText = (e: unknown) => {
  const x = explainError(e, e instanceof Error ? e.message : String(e))
  return x.reason ? `${x.text} (${x.reason})` : x.text
}

// ---- master pause and restore ----
export const writeAutopilot = (paused: boolean, reason?: string | null) =>
  unwrap(
    api.PUT("/api/autopilot", {
      body: { paused, reason: reason?.trim() ? reason.trim() : null },
    })
  )

export const restoreQuery = () =>
  queryOptions({
    queryKey: apKeys.restore,
    queryFn: () => unwrap(api.GET("/api/autopilot/restore")),
  })

export const resumeAfterRestore = () =>
  unwrap(api.POST("/api/autopilot/resume-after-restore"))

// ---- policy ----
export const campaignsQuery = () =>
  queryOptions({
    queryKey: apKeys.campaigns,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/campaigns", { params: { query: { limit: 200 } } })
        )
      ).items,
  })

export const settingsQuery = () =>
  queryOptions({
    queryKey: apKeys.settings,
    queryFn: async () => {
      const groups = (await unwrap(api.GET("/api/settings"))).groups
      const out: Record<string, SettingOut> = {}
      for (const g of groups) for (const s of g.settings) out[s.key] = s
      return out
    },
  })

export const putSetting = (key: string, value: unknown, reason?: string) =>
  unwrap(
    api.PUT("/api/settings/{key}", {
      params: { path: { key } },
      body: { value: value as never, reason: reason ?? null },
    })
  )

/** Save only the automation policy of a campaign: the rest of the campaign is sent back unchanged. */
export const saveAutomation = (c: CampaignOut, automation: AutomationPolicy) =>
  unwrap(
    api.PUT("/api/campaigns/{item_id}", {
      params: { path: { item_id: c.id } },
      body: {
        name: c.name,
        track_id: c.track_id ?? null,
        priority: c.priority ?? 0,
        criteria: c.criteria as never,
        unknown_data_policy: c.unknown_data_policy,
        rubric_id: c.rubric_id ?? null,
        automation,
        budget: c.budget,
        source_ids: c.source_ids ?? [],
        schedule_cron: c.schedule_cron ?? null,
        preferred_seniority: c.preferred_seniority ?? null,
      },
    })
  )

export const runnersQuery = () =>
  queryOptions({
    queryKey: apKeys.runners,
    queryFn: () => unwrap(api.GET("/api/tokens/runners")),
  })

// ---- approvals ----
/** Applications waiting on the owner: stage "ready". */
export const approvalQueueQuery = () =>
  queryOptions({
    queryKey: apKeys.queue,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/applications", {
            params: { query: { stage: "ready", limit: 200 } },
          })
        )
      ).items,
  })

export const receiptQuery = (id: string) =>
  queryOptions({
    queryKey: apKeys.receipt(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/applications/{application_id}/receipt", {
          params: { path: { application_id: id } },
        })
      ),
  })

export const packetsQuery = (id: string) =>
  queryOptions({
    queryKey: apKeys.packets(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/applications/{application_id}/packets", {
          params: { path: { application_id: id } },
        })
      ),
  })

export const approvePacket = (
  id: string,
  packet: PacketOut,
  channel: Channel
) =>
  unwrap(
    api.POST("/api/applications/{application_id}/approve", {
      params: { path: { application_id: id } },
      body: {
        packet_version: packet.version,
        packet_hash: packet.content_hash,
        channel,
      },
    })
  )

/** The current packet, or null when none has been built (404). */
export const currentPacketQuery = (id: string) =>
  queryOptions({
    queryKey: apKeys.packet(id),
    queryFn: async (): Promise<PacketOut | null> => {
      try {
        return await unwrap(
          api.GET("/api/applications/{application_id}/packet", {
            params: { path: { application_id: id } },
          })
        )
      } catch (e) {
        if (isApiError(e, 404)) return null
        throw e
      }
    },
  })

/** Say no: the role is skipped and the next role at the employer is promoted. */
export const rejectApplication = (id: string, reason: string | null) =>
  unwrap(
    api.POST("/api/applications/{application_id}/reject", {
      params: { path: { application_id: id } },
      body: { reason },
    })
  )

/** Retire the packet and send the application back to tailoring with a note. */
export const requestChanges = (id: string, note: string) =>
  unwrap(
    api.POST("/api/applications/{application_id}/request-changes", {
      params: { path: { application_id: id } },
      body: { note },
    })
  )

/** Held runner-up roles: every job in the list whose conflict state is "held". */
export const heldRolesQuery = () =>
  queryOptions({
    queryKey: apKeys.held,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/jobs", { params: { query: { limit: 200 } } })
        )
      ).items.filter((j) => j.conflict_state === "held"),
  })

// ---- dispatch ----
export const dispatchAppsQuery = () =>
  queryOptions({
    queryKey: apKeys.dispatchApps,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/applications", { params: { query: { limit: 200 } } })
        )
      ).items.filter((a) =>
        ["applying", "submitted_unconfirmed", "submitted"].includes(a.stage)
      ),
  })

export const dispatchesQuery = (id: string) =>
  queryOptions({
    queryKey: apKeys.dispatches(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/applications/{application_id}/dispatches", {
          params: { path: { application_id: id } },
        })
      ),
  })

export const cancelDispatch = (applicationId: string, dispatchId: string) =>
  unwrap(
    api.POST(
      "/api/applications/{application_id}/dispatches/{dispatch_id}/cancel",
      {
        params: {
          path: { application_id: applicationId, dispatch_id: dispatchId },
        },
      }
    )
  )

/** Send the current approved packet: permit, then the attempt (manual is handed off at once). */
export const createDispatch = (id: string) =>
  unwrap(
    api.POST("/api/applications/{application_id}/dispatches", {
      params: { path: { application_id: id } },
      body: {},
    })
  )

/** Settle one uncertain attempt: ask its channel now, or record that it went out or did not. */
export const reconcileDispatch = (
  applicationId: string,
  dispatchId: string,
  body: ReconcileIn
) =>
  unwrap(
    api.POST(
      "/api/applications/{application_id}/dispatches/{dispatch_id}/reconcile",
      {
        params: {
          path: { application_id: applicationId, dispatch_id: dispatchId },
        },
        body,
      }
    )
  )

// ---- handoff ----
export const handoffQuery = (id: string) =>
  queryOptions({
    queryKey: apKeys.handoff(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/applications/{application_id}/handoff", {
          params: { path: { application_id: id } },
        })
      ),
  })

// ---- pending actions ----
/** Open pending actions; `kind` narrows to one exact blocker kind (`?kind=`). */
export const pendingQuery = (kind: string | null = null) =>
  queryOptions({
    queryKey: kind ? [...apKeys.pending, kind] : apKeys.pending,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/pending-actions", {
            params: {
              query: kind
                ? { status: "open", limit: 200, kind }
                : { status: "open", limit: 200 },
            },
          })
        )
      ).items,
  })

/** The wave 1 resolve call, shared with Today. */
export const resolvePending = (id: string, body: ResolveIn) =>
  resolveAction(id, body)

// ---- trusted sites ----
export const trustedQuery = () =>
  queryOptions({
    queryKey: apKeys.trusted,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/trusted-sites", { params: { query: { limit: 200 } } })
        )
      ).items,
  })

export const addTrusted = (body: Schemas["TrustedSiteIn"]) =>
  unwrap(api.POST("/api/trusted-sites", { body }))

export const removeTrusted = (id: string) =>
  unwrap(
    api.DELETE("/api/trusted-sites/{item_id}", {
      params: { path: { item_id: id } },
    })
  )
