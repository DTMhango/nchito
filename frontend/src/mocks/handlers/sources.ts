import { delay, http, HttpResponse } from "msw"
import type {
  Detected,
  Employer,
  EmployerInput,
  Run,
  RunCreate,
  Schedule,
  ScheduleInput,
  Source,
  SourceInput,
} from "@/features/sources/api"
import { db } from "../db"
import { PROPOSED, store, tickRun, withNext } from "@/mocks/dataset/sources"
import { settingValues } from "@/mocks/dataset/settings"
import { aiMockState } from "./ai"

const latency = () =>
  import.meta.env.MODE === "test" ? Promise.resolve() : delay(120)
const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const notFound = (what: string) =>
  HttpResponse.json({ detail: `${what} not found.` }, { status: 404 })
const page = <T>(items: T[]) =>
  HttpResponse.json({ items, total: items.length, next_cursor: null })
const id = (p: string) => `${p}-${Math.random().toString(36).slice(2, 8)}`
const now = () => new Date().toISOString()

const BOARDS: {
  re: RegExp
  connector: string
  slug: (m: RegExpExecArray) => string
}[] = [
  {
    re: /(?:boards|job-boards)\.greenhouse\.io\/([\w-]+)/i,
    connector: "greenhouse",
    slug: (m) => m[1],
  },
  { re: /jobs\.lever\.co\/([\w-]+)/i, connector: "lever", slug: (m) => m[1] },
  {
    re: /jobs\.ashbyhq\.com\/([\w.-]+)/i,
    connector: "ashby",
    slug: (m) => m[1],
  },
  {
    re: /apply\.workable\.com\/([\w-]+)/i,
    connector: "workable",
    slug: (m) => m[1],
  },
  {
    re: /([\w-]+)\.wd\d+\.myworkdayjobs\.com\/(?:[a-z]{2}-[A-Z]{2}\/)?([\w-]+)/i,
    connector: "workday",
    slug: (m) => `${m[1]}/${m[2]}`,
  },
]

function detect(url: string): Detected {
  for (const b of BOARDS) {
    const m = b.re.exec(url)
    if (m) {
      const slug = b.slug(m)
      const name = slug
        .split("/")[0]
        .split(/[-_]/)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ")
      return {
        connector: b.connector,
        board_slug: slug,
        employer_name: name,
        confidence: 0.97,
      }
    }
  }
  return {
    connector: null,
    board_slug: null,
    employer_name: null,
    confidence: 0,
  }
}

/** How each wave 3 connector reads (the server refuses any other access). */
const WAVE3_ACCESS: Record<string, Source["access"]> = {
  jobspy: "html",
  careers_page: "html",
  web_search: "api",
}
const httpUrl = (v: unknown) => /^https?:\/\/[^/\s]+/.test(String(v ?? ""))

/** The connector's `validate_config` (jobspy.py, careers_page.py, web_search.py), in short. */
function checkSource(body: SourceInput): string | null {
  const access = WAVE3_ACCESS[body.connector]
  if (!access) return null
  if (body.access !== access)
    return `connector '${body.connector}' reads by ${access}, not ${body.access}`
  const c = body.config ?? {}
  if (body.connector === "jobspy" && !store.jobspyInstalled)
    return "JobSpy is not installed on this server (pip install 'nchito[jobspy]')"
  if (body.connector === "careers_page") {
    const list = (c.employers ?? c.urls) as unknown
    if (!Array.isArray(list) || !list.length)
      return "employers must list at least one careers page URL"
    for (const e of list) {
      const url = typeof e === "string" ? e : (e as { url?: unknown }).url
      if (!httpUrl(url)) return `'${String(url)}' is not an http(s) URL`
    }
  }
  if (body.connector === "web_search") {
    if (!httpUrl(c.endpoint))
      return `'${String(c.endpoint ?? "")}' is not an http(s) URL`
    if (c.key_header && c.key_param)
      return "give the key as a header or a query parameter, not both"
  }
  return null
}

/** The search API key a web search source would get (its connection, else the first enabled one). */
function hasSearchKey(config: Record<string, unknown>): boolean {
  const search = aiMockState().connections.filter(
    (c) => c.provider === "search_api"
  )
  const own = config.connection_id
    ? search.find((c) => c.id === config.connection_id)
    : search.find((c) => c.enabled)
  return !!own?.enabled
}

/** A wave 3 connector's test failure, as the server words it, or null. */
function wave3TestError(s: Source): string | null {
  if (s.connector === "jobspy") {
    if (!store.jobspyInstalled)
      return "ValueError: JobSpy is not installed on this server (pip install 'nchito[jobspy]')"
    const on = s.config?.enabled ?? settingValues["sources.jobspy.enabled"]
    if (!on)
      return "SourceError: JobSpy is switched off (setting sources.jobspy.enabled)"
  }
  if (s.connector === "web_search" && !hasSearchKey(s.config ?? {}))
    return "SourceError: no API key: connect the search provider first"
  return null
}

export const sourcesHandlers = [
  // ---- missed-run policy ----

  // ---- sources ----
  http.get("*/api/sources", async () => {
    if (!db.get().session) return unauthorized()
    await latency()
    return page(store.sources)
  }),
  http.post("*/api/sources", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as SourceInput
    const err = checkSource(body)
    if (err) return HttpResponse.json({ detail: err }, { status: 422 })
    const created: Source = {
      id: id("src"),
      created_at: now(),
      updated_at: now(),
      connector: body.connector,
      name: body.name,
      access: body.access,
      config: body.config ?? {},
      access_notes: body.access_notes ?? null,
      rate_limit: body.rate_limit ?? { requests_per_minute: 10, burst: 2 },
      permitted_actions: body.permitted_actions ?? [
        "search",
        "fetch",
        "check_open",
      ],
      enabled: body.enabled ?? true,
      health: { status: "unknown", consecutive_failures: 0, last_error: null },
      last_success_at: null,
    }
    store.sources = [...store.sources, created]
    return HttpResponse.json(created, { status: 201 })
  }),
  http.post("*/api/sources/detect", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const { url } = (await request.json()) as { url: string }
    return HttpResponse.json(detect(url))
  }),
  http.put("*/api/sources/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as SourceInput
    const cur = store.sources.find((s) => s.id === params.id)
    if (!cur) return notFound("Source")
    const err = checkSource(body)
    if (err) return HttpResponse.json({ detail: err }, { status: 422 })
    const next: Source = { ...cur, ...body, updated_at: now() } as Source
    store.sources = store.sources.map((s) => (s.id === cur.id ? next : s))
    return HttpResponse.json(next)
  }),
  http.post("*/api/sources/:id/test", async ({ params }) => {
    if (!db.get().session) return unauthorized()
    await delay(import.meta.env.MODE === "test" ? 0 : 700)
    const s = store.sources.find((x) => x.id === params.id)
    if (!s) return notFound("Source")
    const wave3 = wave3TestError(s)
    if (wave3)
      return HttpResponse.json({
        ok: false,
        sample_count: 0,
        sample_titles: [],
        error: wave3,
      })
    if (s.health.status === "failing")
      return HttpResponse.json({
        ok: false,
        sample_count: 0,
        sample_titles: [],
        error: s.health.last_error ?? "HTTP 403 Forbidden",
      })
    return HttpResponse.json({
      ok: true,
      sample_count: 3,
      sample_titles: [
        "Senior Actuarial Analyst",
        "Reinsurance Pricing Lead",
        "Risk Data Engineer",
      ],
      error: null,
    })
  }),

  // ---- watched employers ----
  http.get("*/api/watched-employers", async () => {
    if (!db.get().session) return unauthorized()
    await latency()
    return page(store.employers)
  }),
  http.post("*/api/watched-employers", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as EmployerInput
    const e: Employer = {
      ...body,
      priority: body.priority ?? 3,
      cooldown_days: body.cooldown_days ?? null,
      always_ask_first: body.always_ask_first ?? false,
      id: id("emp"),
      created_at: now(),
      updated_at: now(),
    }
    store.employers = [...store.employers, e]
    return HttpResponse.json(e, { status: 201 })
  }),
  http.put("*/api/watched-employers/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as EmployerInput
    const cur = store.employers.find((e) => e.id === params.id)
    if (!cur) return notFound("Employer")
    const next = { ...cur, ...body, updated_at: now() }
    store.employers = store.employers.map((e) => (e.id === cur.id ? next : e))
    return HttpResponse.json(next)
  }),
  http.delete("*/api/watched-employers/:id", async ({ params }) => {
    if (!db.get().session) return unauthorized()
    store.employers = store.employers.filter((e) => e.id !== params.id)
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- schedules ----
  http.get("*/api/schedules", async () => {
    if (!db.get().session) return unauthorized()
    await latency()
    return page(store.schedules)
  }),
  http.post("*/api/schedules", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as ScheduleInput
    const s: Schedule = withNext({
      ...body,
      campaign_id: body.campaign_id ?? null,
      timezone: body.timezone ?? null,
      enabled: body.enabled ?? true,
      dry_run: body.dry_run ?? false,
      id: id("sch"),
      created_at: now(),
      updated_at: now(),
      next_run_at: null,
      last_enqueued_at: null,
      last_run_id: null,
    })
    store.schedules = [...store.schedules, s]
    return HttpResponse.json(s, { status: 201 })
  }),
  http.put("*/api/schedules/:id", async ({ params, request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as ScheduleInput
    const cur = store.schedules.find((s) => s.id === params.id)
    if (!cur) return notFound("Schedule")
    const next = withNext({ ...cur, ...body, updated_at: now() })
    store.schedules = store.schedules.map((s) => (s.id === cur.id ? next : s))
    return HttpResponse.json(next)
  }),
  http.delete("*/api/schedules/:id", async ({ params }) => {
    if (!db.get().session) return unauthorized()
    store.schedules = store.schedules.filter((s) => s.id !== params.id)
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- runs ----
  http.get("*/api/runs", async () => {
    if (!db.get().session) return unauthorized()
    await latency()
    store.runs.forEach((r) => tickRun(r))
    return page(store.runs)
  }),
  http.post("*/api/runs", async ({ request }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const body = (await request.json()) as RunCreate
    const run: Run = {
      id: id("run"),
      created_at: now(),
      updated_at: now(),
      kind: body.kind,
      trigger: "manual",
      campaign_id: body.campaign_id ?? null,
      schedule_id: null,
      scheduled_for: null,
      dry_run: body.dry_run ?? false,
      counts: {},
      proposed_actions: body.dry_run ? PROPOSED : [],
      source_results: [],
      cost_minor: 0,
      cost_micros: 0,
      config_versions: {},
      status: "queued",
      started_at: now(),
      finished_at: null,
      error: null,
    }
    store.runs = [run, ...store.runs]
    store.live.set(run.id, Date.now())
    return HttpResponse.json(run, { status: 201 })
  }),
  http.get("*/api/runs/:id", async ({ params }) => {
    if (!db.get().session) return unauthorized()
    await latency()
    const r = store.runs.find((x) => x.id === params.id)
    if (!r) return notFound("Run")
    return HttpResponse.json(tickRun(r))
  }),
  http.post("*/api/runs/:id/cancel", async ({ params }) => {
    if (!db.get().session) return unauthorized()
    const r = store.runs.find((x) => x.id === params.id)
    if (!r) return notFound("Run")
    store.live.delete(r.id)
    const next: Run = { ...r, status: "cancelled", finished_at: now() }
    store.runs = store.runs.map((x) => (x.id === r.id ? next : x))
    return HttpResponse.json(next)
  }),

  // ---- event stream: announces when mock runs start and finish ----
  http.get("*/api/events", () => {
    const enc = new TextEncoder()
    let timer: ReturnType<typeof setInterval> | undefined
    const seen = new Set<string>()
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(enc.encode("retry: 5000\n\n"))
        timer = setInterval(() => {
          for (const r of store.runs) {
            const live = store.live.has(r.id)
            if (live && !seen.has(r.id)) {
              seen.add(r.id)
              c.enqueue(
                enc.encode(
                  `event: run.started\ndata: ${JSON.stringify({ data: { run_id: r.id }, at: now() })}\n\n`
                )
              )
            }
            if (!live && seen.has(r.id)) {
              seen.delete(r.id)
              c.enqueue(
                enc.encode(
                  `event: run.finished\ndata: ${JSON.stringify({ data: { run_id: r.id, status: r.status }, at: now() })}\n\n`
                )
              )
            }
          }
        }, 1000)
      },
      cancel() {
        clearInterval(timer)
      },
    })
    return new HttpResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
    })
  }),
]
