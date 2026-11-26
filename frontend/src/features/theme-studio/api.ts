/** Typed calls for the theme studio (CONTRACTS "Wave 4 themes additions"). */
import { queryOptions, type QueryClient } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import { keys } from "@/lib/api/endpoints"
import type { Schemas } from "@/lib/api/types"

export type ThemeOut = Schemas["ThemeOut"]
export type ThemeBody = Schemas["ThemeBody"]
export type ThemeRevision = Schemas["ThemeRevisionOut"]
export type LowContrastPair = {
  mode: string
  fg: string
  bg: string
  ratio: number
}

const path = (id: string) => ({ params: { path: { theme_id: id } } })

export const studioKeys = {
  themes: ["themes", "studio"] as const,
  revisions: (id: string) => ["themes", "revisions", id] as const,
  setting: (key: string) => ["settings", "value", key] as const,
}

export const studioThemesQuery = () =>
  queryOptions({
    queryKey: studioKeys.themes,
    queryFn: () => unwrap(api.GET("/api/themes")),
  })

export const revisionsQuery = (id: string, enabled = true) =>
  queryOptions({
    queryKey: studioKeys.revisions(id),
    queryFn: () =>
      unwrap(api.GET("/api/themes/{theme_id}/revisions", path(id))),
    enabled,
  })

/** A runtime setting's current value (studio limits live in the settings registry). */
export const settingValueQuery = (key: string) =>
  queryOptions({
    queryKey: studioKeys.setting(key),
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/settings/{key}", { params: { path: { key } } })
        )
      ).value as unknown,
    staleTime: 60_000,
  })

/** Only the ThemeBody fields: ThemeIn forbids anything else. */
export function toBody(t: ThemeBody | ThemeOut): ThemeBody {
  return {
    name: t.name,
    description: t.description ?? null,
    fonts: t.fonts,
    radius: t.radius,
    density: t.density,
    light: t.light,
    dark: t.dark,
    chart: t.chart,
    score: t.score,
  }
}

export const saveTheme = (id: string, body: ThemeBody, accept: boolean) =>
  unwrap(
    api.PUT("/api/themes/{theme_id}", {
      ...path(id),
      body: { ...body, accept_low_contrast: accept },
    })
  )
export const duplicateTheme = (id: string, name?: string) =>
  unwrap(
    api.POST("/api/themes/{theme_id}/duplicate", {
      ...path(id),
      body: { name: name ?? null },
    })
  )
export const deleteStudioTheme = (id: string) =>
  unwrap(api.DELETE("/api/themes/{theme_id}", path(id)))
export const setDefaultTheme = (id: string) =>
  unwrap(api.PUT("/api/themes/{theme_id}/default", path(id)))
export const undoTheme = (id: string) =>
  unwrap(api.POST("/api/themes/{theme_id}/undo", path(id)))
export const redoTheme = (id: string) =>
  unwrap(api.POST("/api/themes/{theme_id}/redo", path(id)))
export const restoreRevision = (id: string, n: number) =>
  unwrap(
    api.POST("/api/themes/{theme_id}/revisions/{number}/restore", {
      params: { path: { theme_id: id, number: n } },
    })
  )
export const exportTheme = (id: string) =>
  unwrap(api.GET("/api/themes/{theme_id}/export", path(id)))

/** Upload an untrusted theme file as raw JSON text; the server validates it strictly. */
export const importThemeFile = (text: string, accept: boolean) =>
  unwrap(
    api.POST("/api/themes/import", {
      params: { query: { accept_low_contrast: accept } },
      body: text as unknown as Record<string, never>,
      bodySerializer: (b: unknown) => b as string,
      headers: { "content-type": "application/json" },
    })
  )

/** After any theme change: the app's theme list and the studio's. */
export function invalidateThemes(qc: QueryClient, id?: string) {
  void qc.invalidateQueries({ queryKey: keys.themes })
  if (id) void qc.invalidateQueries({ queryKey: studioKeys.revisions(id) })
}

export function downloadJson(fileName: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}

export const fileSlug = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "theme"
