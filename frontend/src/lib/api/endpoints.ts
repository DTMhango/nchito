/**
 * One function per endpoint, plus TanStack Query keys and options.
 * Feature code imports from here, never from openapi-fetch directly.
 */
import { queryOptions } from "@tanstack/react-query"
import { api, ApiError, unwrap } from "./client"
import type {
  Appearance,
  AutopilotState,
  JobCaptureRequest,
  LoginRequest,
  Me,
  OwnerCreate,
  Schemas,
  Theme,
  ThemeInput,
} from "./types"

export const keys = {
  setup: ["setup", "status"] as const,
  me: ["auth", "me"] as const,
  themes: ["themes"] as const,
  appearance: ["settings", "appearance"] as const,
  autopilot: ["autopilot"] as const,
  health: ["health"] as const,
}

// ---- setup and auth ----
export const getSetupStatus = () => unwrap(api.GET("/api/setup/status"))
export const createOwner = (body: OwnerCreate) =>
  unwrap(api.POST("/api/setup/owner", { body }))
export const login = (body: LoginRequest) =>
  unwrap(api.POST("/api/auth/login", { body }))
export const logout = () => unwrap(api.POST("/api/auth/logout"))

/** The signed-in owner, or null when there is no session (401). */
export async function getMe(): Promise<Me | null> {
  try {
    return await unwrap(api.GET("/api/auth/me"))
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null
    throw e
  }
}

export const setupStatusQuery = () =>
  queryOptions({
    queryKey: keys.setup,
    queryFn: getSetupStatus,
    staleTime: 60_000,
  })
export const meQuery = () =>
  queryOptions({ queryKey: keys.me, queryFn: getMe, staleTime: 5 * 60_000 })

// ---- themes and appearance ----
type ThemeOut = Schemas["ThemeOut"]
type AppearanceOut = Schemas["Appearance"]
/** The contract sends `description: null`; the theme engine's schema leaves it out. */
const toTheme = ({ description, ...t }: ThemeOut): Theme => ({
  ...t,
  ...(description ? { description } : {}),
})
/** Appearance is a request shape too, so the contract marks its nullable fields optional. */
const toAppearance = (a: AppearanceOut): Appearance => ({
  ...a,
  radius: a.radius ?? null,
  accent_override: a.accent_override ?? null,
})

export const listThemes = async () =>
  (await unwrap(api.GET("/api/themes"))).map(toTheme)
export const createTheme = async (body: ThemeInput) =>
  toTheme(await unwrap(api.POST("/api/themes", { body })))
export const updateTheme = async (id: string, body: ThemeInput) =>
  toTheme(
    await unwrap(
      api.PUT("/api/themes/{theme_id}", {
        params: { path: { theme_id: id } },
        body,
      })
    )
  )
export const deleteTheme = (id: string) =>
  unwrap(
    api.DELETE("/api/themes/{theme_id}", { params: { path: { theme_id: id } } })
  )
export const getAppearance = async () =>
  toAppearance(await unwrap(api.GET("/api/settings/appearance")))
export const putAppearance = (body: Appearance) =>
  unwrap(api.PUT("/api/settings/appearance", { body }))

export const themesQuery = (enabled = true) =>
  queryOptions<Theme[]>({
    queryKey: keys.themes,
    queryFn: listThemes,
    enabled,
    staleTime: 10 * 60_000,
    retry: false,
  })
export const appearanceQuery = (enabled = true) =>
  queryOptions<Appearance>({
    queryKey: keys.appearance,
    queryFn: getAppearance,
    enabled,
    retry: false,
  })

// ---- health ----
export const getHealth = () => unwrap(api.GET("/api/health"))

// ---- capture and Autopilot ----
export const captureJob = (body: JobCaptureRequest) =>
  unwrap(api.POST("/api/jobs/capture", { body }))
export const getAutopilot = () => unwrap(api.GET("/api/autopilot"))
export const setAutopilotPaused = (paused: boolean) =>
  unwrap(api.PUT("/api/autopilot", { body: { paused } }))

export const autopilotQuery = () =>
  queryOptions<AutopilotState>({
    queryKey: keys.autopilot,
    queryFn: getAutopilot,
    retry: false,
    staleTime: 30_000,
  })
