/**
 * Autopilot, approvals, dispatch, handoff, pending actions and trusted sites: typed against
 * the generated contract. Components import from here, never from openapi-fetch.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"

export type PacketOut = Schemas["PacketOut"]
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
  dispatchApps: ["autopilot", "dispatch-apps"] as const,
  held: ["autopilot", "held-roles"] as const,
  pending: ["autopilot", "pending"] as const,
  trusted: ["autopilot", "trusted-sites"] as const,
}

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

export const moveApplication = (
  id: string,
  stage: "skipped" | "tailoring",
  note: string
) =>
  unwrap(
    api.POST("/api/applications/{application_id}/stage", {
      params: { path: { application_id: id } },
      body: { stage, note },
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

export const markSent = (id: string, reference: string | null, note: string) =>
  unwrap(
    api.POST("/api/applications/{application_id}/mark-submitted", {
      params: { path: { application_id: id } },
      body: { reference, note },
    })
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
export const pendingQuery = () =>
  queryOptions({
    queryKey: apKeys.pending,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/pending-actions", {
            params: { query: { status: "open", limit: 200 } },
          })
        )
      ).items,
  })

export const resolvePending = (id: string, body: ResolveIn) =>
  unwrap(
    api.POST("/api/pending-actions/{action_id}/resolve", {
      params: { path: { action_id: id } },
      body,
    })
  )

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
