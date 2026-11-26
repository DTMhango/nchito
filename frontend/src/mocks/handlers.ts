import { delay, http, HttpResponse } from "msw"
import { appearanceSchema } from "@/themes/schema"
import type {
  JobCaptureRequest,
  LoginRequest,
  OwnerCreate,
} from "@/lib/api/types"
import { db } from "./db"
import { aiHandlers } from "./handlers/ai"
import { dataHandlers } from "./handlers/data"
import { kitHandlers } from "./handlers/kit"
import { sourcesHandlers } from "./handlers/sources"
import { campaignHandlers } from "./handlers/campaigns"
import { applicationsHandlers } from "./handlers/applications"
import { jobHandlers } from "./handlers/jobs"
import { settingsHandlers } from "./handlers/settings"
import { matchesHandlers } from "./handlers/matches"
import { studioHandlers } from "./handlers/studio"
import { autopilotHandlers } from "./handlers/autopilot"
import { w3JobUiHandlers } from "./handlers/w3-job-ui"
import { runnersHandlers } from "./handlers/runners"
import { insightsHandlers } from "./handlers/insights"
import { themesHandlers } from "./handlers/themes"
import { calendarHandlers } from "./handlers/calendar"
import { preferencesHandlers } from "./handlers/preferences"
import { bulkHandlers } from "./handlers/bulk"

const latency = () =>
  import.meta.env.MODE === "test" ? Promise.resolve() : delay(120)
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
export const handlers = [
  // Explicit order (MSW: first matching handler that returns a response wins).
  // 1. Studio: spec, checks, tailor, documents; its packets handler answers only for
  //    applications it has packets for and returns undefined otherwise.
  // 2. Autopilot: approvals, packets, dispatches, pause; beats the wave 0 autopilot stub below.
  ...studioHandlers,
  ...runnersHandlers,
  ...insightsHandlers,
  ...autopilotHandlers,
  // Wave 3 job page: interview pack, compare, posting changes (before the generic /api/jobs/:id).
  ...w3JobUiHandlers,
  // Wave 4 calendar: events, upcoming, the feed and the Google Calendar toggle (before the connections handlers).
  ...calendarHandlers,
  // Wave 4 feedback: thumbs, preference suggestions, policy preview.
  ...preferencesHandlers,
  // Wave 4 bulk actions and employers (their own paths; no overlap).
  ...bulkHandlers,
  // Data, non-AI connections and health: before the AI handlers (they fall through for LLM providers).
  ...dataHandlers,
  ...kitHandlers,
  ...sourcesHandlers,
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
      totp_enabled: owner.totp_secret !== null,
    })
  }),

  // ---- themes and the theme studio ----
  ...themesHandlers,

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
  // PUT /api/autopilot is served by the autopilot handlers (pause effects, restore lock).
  ...aiHandlers,
  ...campaignHandlers,

  // Today, applications, pending actions (wave 1). Last, so other streams' handlers win on overlap.
  ...applicationsHandlers,
  ...jobHandlers,
  ...settingsHandlers,

  ...matchesHandlers,
]
