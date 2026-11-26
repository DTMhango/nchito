import createClient from "openapi-fetch"
import type { ApiErrorBody, paths } from "./types"

/** An HTTP error from the API, with the parsed body when there is one. */
export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody | undefined

  constructor(status: number, body: unknown) {
    super(messageFrom(status, body as ApiErrorBody | undefined))
    this.name = "ApiError"
    this.status = status
    this.body = body as ApiErrorBody | undefined
  }
}

function messageFrom(status: number, body: ApiErrorBody | undefined): string {
  const d = body?.detail
  if (typeof d === "string") return d
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  if (status === 401) return "Your session has ended. Sign in again."
  if (status === 429) return "Too many attempts. Wait a minute and try again."
  if (status >= 500) return "The server had a problem. Try again in a moment."
  return `Request failed (${status})`
}

export const isApiError = (e: unknown, status?: number): e is ApiError =>
  e instanceof ApiError && (status === undefined || e.status === status)

const origin =
  typeof window !== "undefined" ? window.location.origin : "http://localhost"

/**
 * The one typed client (generated `paths`). Same-origin: in dev Vite proxies /api to the backend, in production the
 * backend serves the SPA. Cookies carry the session.
 */
export const api = createClient<paths>({
  baseUrl: origin,
  credentials: "include",
  // Resolve fetch at call time so test interceptors (MSW) installed later still apply.
  fetch: (request: Request) => globalThis.fetch(request),
})

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Await an openapi-fetch call and return its data, or throw ApiError. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok) throw new ApiError(response.status, error)
  return data as T
}

/**
 * `bodySerializer` for multipart endpoints: each field becomes a form part; arrays repeat
 * the field (FastAPI's `list[UploadFile]`), null and undefined are left out.
 */
export function toFormData(body: object): FormData {
  const form = new FormData()
  for (const [key, value] of Object.entries(body)) {
    const values = Array.isArray(value) ? value : [value]
    for (const v of values) {
      if (v === undefined || v === null) continue
      form.append(key, v instanceof Blob ? v : String(v))
    }
  }
  return form
}
