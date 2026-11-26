/**
 * Typed calls for the settings screens, against the generated contract (`schema.d.ts`).
 * The shared client is cast to the generated `paths` so nothing else has to change.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

const gen = api

export type SettingOut = components["schemas"]["SettingOut"]
export type SettingGroupOut = components["schemas"]["SettingGroupOut"]
export type SettingRevision = components["schemas"]["SettingRevisionOut"]
export type AuditEvent = components["schemas"]["AuditEventOut"]
export type ConfigRevision = components["schemas"]["ConfigRevisionOut"]

export const settingsKeys = {
  all: ["settings", "registry"] as const,
  history: (key: string) => ["settings", "history", key] as const,
  audit: (f: AuditFilters) => ["audit", f] as const,
  config: (kind: string) => ["config-history", kind] as const,
}

export type AuditFilters = {
  action?: string
  actor?: string
  subject_type?: string
}

export const settingsQuery = () =>
  queryOptions({
    queryKey: settingsKeys.all,
    queryFn: async () => (await unwrap(gen.GET("/api/settings"))).groups,
  })

export const putSetting = (key: string, value: unknown, reason?: string) =>
  unwrap(
    gen.PUT("/api/settings/{key}", {
      params: { path: { key } },
      body: { value, reason: reason ?? null },
    })
  )

export const settingHistory = (key: string) =>
  unwrap(gen.GET("/api/settings/{key}/history", { params: { path: { key } } }))

export const listAudit = (f: AuditFilters, before?: string) =>
  unwrap(
    gen.GET("/api/audit", {
      params: {
        query: {
          limit: 25,
          before: before ?? undefined,
          action: f.action || undefined,
          actor: f.actor || undefined,
          subject_type: f.subject_type || undefined,
        },
      },
    })
  )

export const listConfigHistory = (kind: string, cursor?: string) =>
  unwrap(
    gen.GET("/api/data/config-history", {
      params: {
        query: { kind: kind || undefined, cursor: cursor ?? undefined },
      },
    })
  )

export const rollbackRevision = (id: string, note: string) =>
  unwrap(
    gen.POST("/api/data/config-history/{revision_id}/rollback", {
      params: { path: { revision_id: id } },
      body: { note: note || null },
    })
  )

export const changePassword = (
  current_password: string,
  new_password: string
) =>
  unwrap(
    gen.POST("/api/auth/password", { body: { current_password, new_password } })
  )
export const totpSetup = () => unwrap(gen.POST("/api/auth/totp/setup"))
export const totpEnable = (code: string) =>
  unwrap(gen.POST("/api/auth/totp/enable", { body: { code } }))
export const totpDisable = (password: string, code: string) =>
  unwrap(gen.POST("/api/auth/totp/disable", { body: { password, code } }))

// ---- sessions (Security) ----
export const sessionsKey = ["auth", "sessions"] as const
export const listSessions = () => unwrap(gen.GET("/api/auth/sessions"))
export const revokeSession = (id: string) =>
  unwrap(
    gen.DELETE("/api/auth/sessions/{session_id}", {
      params: { path: { session_id: id } },
    })
  )
export const revokeOtherSessions = () =>
  unwrap(gen.POST("/api/auth/sessions/revoke-others"))
