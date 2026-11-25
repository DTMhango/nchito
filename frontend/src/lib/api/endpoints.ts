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
export const listThemes = () => unwrap(api.GET("/api/themes"))
export const createTheme = (body: ThemeInput) =>
  unwrap(api.POST("/api/themes", { body }))
export const updateTheme = (id: string, body: ThemeInput) =>
  unwrap(api.PUT("/api/themes/{id}", { params: { path: { id } }, body }))
export const deleteTheme = (id: string) =>
  unwrap(api.DELETE("/api/themes/{id}", { params: { path: { id } } }))
export const getAppearance = () => unwrap(api.GET("/api/settings/appearance"))
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

// ---- PENDING CONTRACT (mocked in MSW; see schema.ts) ----
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
