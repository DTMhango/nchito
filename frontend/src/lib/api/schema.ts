/**
 * HAND-WRITTEN API contract for wave 0, in the shape `openapi-typescript` emits.
 *
 * SWAP SEAM: when the backend publishes its OpenAPI document, generate
 *   npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/schema.gen.ts
 * and change the single re-export in `src/lib/api/types.ts` to point at the generated
 * `paths`. Everything else (client, endpoints, hooks) keeps compiling against `paths`.
 *
 * Endpoints marked PENDING CONTRACT are not in the wave 0 backend. They are served by MSW
 * in mock mode, and the UI degrades gracefully (a toast) when the real backend says 404.
 */
import type { Appearance, Theme } from "@/themes/schema"

type Json<T> = {
  headers: { [name: string]: unknown }
  content: { "application/json": T }
}
type Empty = { headers: { [name: string]: unknown }; content?: never }
type NoParams = { query?: never; header?: never; path?: never; cookie?: never }
type Body<T> = { content: { "application/json": T } }

export type ApiErrorBody = {
  detail?: string | { msg: string; loc?: (string | number)[] }[]
}

export type SetupStatus = { owner_exists: boolean }
export type OwnerCreate = {
  email: string
  password: string
  display_name: string
  timezone: string
}
export type LoginRequest = { email: string; password: string; totp?: string }
export type Me = {
  email: string
  display_name: string
  timezone: string
  app_name: string
}
export type Health = { status: string; [key: string]: unknown }
export type ThemeInput = Omit<Theme, "id" | "builtin"> & { id?: string }

/** PENDING CONTRACT: manual job capture (DESIGN 6, "Manual capture"). */
export type JobCaptureRequest = { url?: string; text?: string }
export type JobCaptureResponse = { id: string; status: "queued" }

/** PENDING CONTRACT: global Autopilot pause (DESIGN 8.1). */
export type AutopilotState = {
  paused: boolean
  paused_at: string | null
  /** What the last pause did. Empty until something has been queued. */
  summary: {
    cancelled: PauseItem[]
    paused: PauseItem[]
    already_out: PauseItem[]
  }
}
export type PauseItem = { id: string; label: string; detail: string }

export interface paths {
  "/api/health": {
    parameters: NoParams
    get: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<Health> }
    }
  }
  "/api/setup/status": {
    parameters: NoParams
    get: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<SetupStatus> }
    }
  }
  "/api/setup/owner": {
    parameters: NoParams
    post: {
      parameters: NoParams
      requestBody: Body<OwnerCreate>
      responses: {
        201: Empty
        409: Json<ApiErrorBody>
        422: Json<ApiErrorBody>
      }
    }
  }
  "/api/auth/login": {
    parameters: NoParams
    post: {
      parameters: NoParams
      requestBody: Body<LoginRequest>
      responses: {
        204: Empty
        401: Json<ApiErrorBody>
        429: Json<ApiErrorBody>
      }
    }
  }
  "/api/auth/logout": {
    parameters: NoParams
    post: {
      parameters: NoParams
      requestBody?: never
      responses: { 204: Empty }
    }
  }
  "/api/auth/me": {
    parameters: NoParams
    get: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<Me>; 401: Json<ApiErrorBody> }
    }
  }
  "/api/themes": {
    parameters: NoParams
    get: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<Theme[]> }
    }
    post: {
      parameters: NoParams
      requestBody: Body<ThemeInput>
      responses: { 201: Json<Theme>; 422: Json<ApiErrorBody> }
    }
  }
  "/api/themes/{id}": {
    parameters: {
      query?: never
      header?: never
      path: { id: string }
      cookie?: never
    }
    put: {
      parameters: {
        query?: never
        header?: never
        path: { id: string }
        cookie?: never
      }
      requestBody: Body<ThemeInput>
      responses: {
        200: Json<Theme>
        403: Json<ApiErrorBody>
        404: Json<ApiErrorBody>
      }
    }
    delete: {
      parameters: {
        query?: never
        header?: never
        path: { id: string }
        cookie?: never
      }
      requestBody?: never
      responses: {
        204: Empty
        403: Json<ApiErrorBody>
        404: Json<ApiErrorBody>
      }
    }
  }
  "/api/settings/appearance": {
    parameters: NoParams
    get: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<Appearance> }
    }
    put: {
      parameters: NoParams
      requestBody: Body<Appearance>
      responses: { 200: Json<Appearance>; 422: Json<ApiErrorBody> }
    }
  }
  "/api/jobs/capture": {
    parameters: NoParams
    post: {
      parameters: NoParams
      requestBody: Body<JobCaptureRequest>
      responses: {
        202: Json<JobCaptureResponse>
        404: Json<ApiErrorBody>
        422: Json<ApiErrorBody>
      }
    }
  }
  "/api/autopilot": {
    parameters: NoParams
    get: {
      parameters: NoParams
      requestBody?: never
      responses: { 200: Json<AutopilotState>; 404: Json<ApiErrorBody> }
    }
    put: {
      parameters: NoParams
      requestBody: Body<{ paused: boolean }>
      responses: { 200: Json<AutopilotState>; 404: Json<ApiErrorBody> }
    }
  }
}
