import { delay, http, HttpResponse } from "msw"
import { BUILTIN_THEMES } from "@/themes"
import { appearanceSchema, themeSchema } from "@/themes/schema"
import type {
  JobCaptureRequest,
  LoginRequest,
  OwnerCreate,
  ThemeInput,
} from "@/lib/api/types"
import { db } from "./db"
import { campaignHandlers } from "./handlers/campaigns"

const latency = () =>
  import.meta.env.MODE === "test" ? Promise.resolve() : delay(120)
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })

export const handlers = [
  http.get("*/api/health", () =>
    HttpResponse.json({ status: "ok", mock: true })
  ),

  // ---- setup ----
  http.get("*/api/setup/status", async () => {
    await latency()
    return HttpResponse.json({ owner_exists: db.get().owner !== null })
  }),
  http.post("*/api/setup/owner", async ({ request }) => {
    await latency()
    if (db.get().owner)
      return HttpResponse.json(
        { detail: "An owner already exists." },
        { status: 409 }
      )
    const body = (await request.json()) as OwnerCreate
    if (!body.email || !body.password || body.password.length < 12) {
      return HttpResponse.json(
        { detail: "Use a password of at least 12 characters." },
        { status: 422 }
      )
    }
    db.update((s) => {
      s.owner = { ...body, totp_secret: null }
      s.session = true
    })
    return new HttpResponse(null, { status: 201 })
  }),

  // ---- auth ----
  http.post("*/api/auth/login", async ({ request }) => {
    await latency()
    const body = (await request.json()) as LoginRequest
    const owner = db.get().owner
    if (
      !owner ||
      owner.email.toLowerCase() !== body.email.trim().toLowerCase() ||
      owner.password !== body.password
    ) {
      return HttpResponse.json(
        { detail: "That email and password don't match." },
        { status: 401 }
      )
    }
    db.update((s) => {
      s.session = true
    })
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/auth/logout", async () => {
    db.update((s) => {
      s.session = false
    })
    return new HttpResponse(null, { status: 204 })
  }),
  http.get("*/api/auth/me", async () => {
    await latency()
    const { owner, session } = db.get()
    if (!owner || !session) return unauthorized()
    return HttpResponse.json({
      email: owner.email,
      display_name: owner.display_name,
      timezone: owner.timezone,
      app_name: "Nchito",
    })
  }),

  // ---- themes ----
  http.get("*/api/themes", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json([...BUILTIN_THEMES, ...db.get().customThemes])
  }),
  http.post("*/api/themes", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const body = (await request.json()) as ThemeInput
    const theme = themeSchema.safeParse({
      ...body,
      id: body.id ?? crypto.randomUUID(),
      builtin: false,
    })
    if (!theme.success)
      return HttpResponse.json(
        { detail: theme.error.issues[0]?.message },
        { status: 422 }
      )
    db.update((s) => {
      s.customThemes.push(theme.data)
    })
    return HttpResponse.json(theme.data, { status: 201 })
  }),
  http.put("*/api/themes/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    if (BUILTIN_THEMES.some((t) => t.id === id))
      return HttpResponse.json(
        { detail: "Built-in themes can't be edited. Duplicate it first." },
        { status: 403 }
      )
    const idx = db.get().customThemes.findIndex((t) => t.id === id)
    if (idx < 0) return notFound("Theme")
    const body = (await request.json()) as ThemeInput
    const theme = themeSchema.parse({ ...body, id, builtin: false })
    db.update((s) => {
      s.customThemes[idx] = theme
    })
    return HttpResponse.json(theme)
  }),
  http.delete("*/api/themes/:id", ({ params }) => {
    if (!db.get().session) return unauthorized()
    const id = String(params.id)
    if (BUILTIN_THEMES.some((t) => t.id === id))
      return HttpResponse.json(
        { detail: "Built-in themes can't be deleted." },
        { status: 403 }
      )
    db.update((s) => {
      s.customThemes = s.customThemes.filter((t) => t.id !== id)
    })
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- appearance ----
  http.get("*/api/settings/appearance", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(db.get().appearance)
  }),
  http.put("*/api/settings/appearance", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const parsed = appearanceSchema.safeParse(await request.json())
    if (!parsed.success)
      return HttpResponse.json(
        { detail: parsed.error.issues[0]?.message },
        { status: 422 }
      )
    db.update((s) => {
      s.appearance = parsed.data
    })
    return HttpResponse.json(parsed.data)
  }),

  // ---- PENDING CONTRACT ----
  http.post("*/api/jobs/capture", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as JobCaptureRequest
    if (!body.url?.trim() && !body.text?.trim())
      return HttpResponse.json(
        { detail: "Paste a link or the posting text." },
        { status: 422 }
      )
    const id = crypto.randomUUID()
    db.update((s) => {
      s.captured.push({ id, ...body })
    })
    return HttpResponse.json({ id, status: "queued" }, { status: 202 })
  }),
  http.get("*/api/autopilot", () => {
    if (!db.get().session) return unauthorized()
    return HttpResponse.json(db.get().autopilot)
  }),
  http.put("*/api/autopilot", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    const { paused } = (await request.json()) as { paused: boolean }
    db.update((s) => {
      s.autopilot.paused = paused
      s.autopilot.paused_at = paused ? new Date().toISOString() : null
    })
    return HttpResponse.json(db.get().autopilot)
  }),
  ...campaignHandlers,
]
