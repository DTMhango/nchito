/**
 * MSW handlers for Settings > AI: provider records, routing, price table, spend, prompts and
 * the budget settings. In-memory, fictional, reset with `resetAiMock()` (tests).
 */
import { settingValues } from "../dataset/settings"
import { http, HttpResponse } from "msw"
import type { components } from "@/lib/api/types"

type S = components["schemas"]

const now = () => new Date().toISOString()
let seq = 0
const uid = () => `00000000-0000-4000-8000-${String(++seq).padStart(12, "0")}`

const STAGES: [string, string][] = [
  ["extract", "ai.model_extract"],
  ["classify_email", "ai.model_classify_email"],
  ["score", "ai.model_score"],
  ["custom_facet", "ai.model_custom_facet"],
  ["tailor", "ai.model_tailor"],
  ["claim_check", "ai.model_claim_check"],
  ["browser_agent", "ai.model_browser_agent"],
  ["interview", "ai.model_tailor"],
  ["import", "ai.model_extract"],
]

const DEFAULT_PROMPTS: Record<string, string> = {
  extract:
    "You extract structured facts from one job posting.\nReport only what the posting states.",
  score:
    "You score how well one job matches the owner's profile and rubric.\nMissing information is unknown, never a match.",
  tailor:
    "You draft tailored application material from approved facts only.\nCite fact codes for every claim.",
  claim_check: "You check generated text against the approved facts it cites.",
  classify_email: "You classify one email received in the job-search mailbox.",
}

type AiState = {
  connections: S["ConnectionOut"][]
  settings: Record<string, unknown>
  prices: S["PriceOut"][]
  prompts: S["PromptOut"][]
  tested: Record<string, { ok: boolean; at: string }>
  spend: S["SpendSummary"]
}

function price(model: string, input: string, output: string): S["PriceOut"] {
  return {
    id: uid(),
    provider: "anthropic",
    model,
    currency: "USD",
    input_per_mtok: input,
    output_per_mtok: output,
    cache_write_per_mtok: null,
    cache_read_per_mtok: null,
    long_context_threshold: null,
    long_input_per_mtok: null,
    long_output_per_mtok: null,
    as_of: "2026-11-03",
    source: "Default list prices",
    updated_at: now(),
  }
}

function seed(): AiState {
  const day = (d: number) => {
    const t = new Date()
    t.setDate(Math.max(1, t.getDate() - d))
    return t.toISOString().slice(0, 10)
  }
  return {
    connections: [],
    // The one settings store (Settings pages own /api/settings); read and written in place.
    settings: settingValues,
    prices: [
      price("claude-haiku-5-5", "10.0000", "50.0000"),
      price("claude-sonnet-5-5", "200.0000", "1000.0000"),
      price("claude-opus-5-5", "400.0000", "2000.0000"),
    ],
    prompts: Object.entries(DEFAULT_PROMPTS).map(([stage, text]) => ({
      id: uid(),
      stage,
      text,
      note: "Default",
      version: 1,
      active: true,
      created_at: now(),
      updated_at: now(),
    })),
    tested: {},
    spend: {
      month: new Date().toISOString().slice(0, 7),
      timezone: "Africa/Lusaka",
      currency: "USD",
      cap_minor: null,
      cap_micros: null,
      per_run_cap_minor: null,
      per_run_cap_micros: null,
      warning_percent: 80,
      month_to_date_minor: 412,
      reserved_minor: 6,
      estimated_unbilled_minor: 35,
      month_to_date_micros: 4_120_000,
      reserved_micros: 60_000,
      estimated_unbilled_micros: 350_000,
      remaining_minor: null,
      remaining_micros: null,
      warning_reached: false,
      by_stage: [
        {
          key: "score",
          billed_minor: 220,
          unbilled_minor: 0,
          billed_micros: 2200000,
          unbilled_micros: 0,
          calls: 310,
        },
        {
          key: "tailor",
          billed_minor: 150,
          unbilled_minor: 35,
          billed_micros: 1500000,
          unbilled_micros: 350000,
          calls: 9,
        },
        {
          key: "extract",
          billed_minor: 42,
          unbilled_minor: 0,
          billed_micros: 420000,
          unbilled_micros: 0,
          calls: 120,
        },
      ],
      by_model: [
        {
          key: "anthropic/claude-haiku-5-5",
          billed_minor: 262,
          billed_micros: 2620000,
          unbilled_minor: 0,
          unbilled_micros: 0,
          calls: 430,
        },
        {
          key: "anthropic/claude-sonnet-5-5",
          billed_minor: 150,
          billed_micros: 1500000,
          unbilled_minor: 0,
          unbilled_micros: 0,
          calls: 6,
        },
        {
          key: "claude_cli/claude-sonnet-5-5",
          billed_minor: 0,
          billed_micros: 0,
          unbilled_minor: 35,
          unbilled_micros: 350000,
          calls: 3,
        },
      ],
      by_run: [],
      daily: [5, 4, 3, 2, 1, 0].map((d, i) => ({
        day: day(d),
        billed_minor: [40, 95, 60, 120, 52, 45][i],
        unbilled_minor: i === 3 ? 35 : 0,
        billed_micros: [40, 95, 60, 120, 52, 45][i] * 10000,
        unbilled_micros: i === 3 ? 350000 : 0,
      })),
    },
  }
}

let state = seed()
export const resetAiMock = () => {
  state = seed()
}
export const aiMockState = () => state

function routes(): S["RouteOut"][] {
  const provider = String(state.settings["ai.provider"])
  return STAGES.map(([stage, key]) => {
    const model = String(state.settings[key])
    const t = state.tested[`${provider}/${model}`]
    return {
      stage,
      setting_key: key,
      provider,
      model,
      billed: provider !== "claude_cli",
      last_test: t ? { ok: t.ok, at: t.at, detail: null } : null,
    }
  })
}

function syncSpend() {
  // Caps are stored in micros; the summary carries them rounded to cents.
  const toMinor = (v: unknown) =>
    v == null ? null : Math.round((v as number) / 10_000)
  const cap = toMinor(state.settings["budget.monthly_cap_micros"])
  state.spend.cap_minor = cap
  state.spend.per_run_cap_minor = toMinor(
    state.settings["budget.per_run_cap_micros"]
  )
  state.spend.warning_percent = state.settings[
    "budget.warning_percent"
  ] as number
  const micros = (v: unknown) => (v == null ? null : (v as number))
  state.spend.cap_micros = micros(state.settings["budget.monthly_cap_micros"])
  state.spend.per_run_cap_micros = micros(
    state.settings["budget.per_run_cap_micros"]
  )
  state.spend.remaining_micros =
    state.spend.cap_micros === null
      ? null
      : Math.max(
          state.spend.cap_micros -
            state.spend.month_to_date_micros -
            state.spend.reserved_micros,
          0
        )
  state.spend.remaining_minor =
    cap === null
      ? null
      : Math.max(
          cap - state.spend.month_to_date_minor - state.spend.reserved_minor,
          0
        )
}

const mask = (s: string) => "********" + s.slice(-4)

export const aiHandlers = [
  http.get("*/api/connections", () => HttpResponse.json(state.connections)),
  http.post("*/api/connections", async ({ request }) => {
    const body = (await request.json()) as S["ConnectionCreate"]
    if (body.provider === "openai_compatible" && !body.config?.base_url)
      return HttpResponse.json(
        { detail: "an OpenAI-compatible provider needs a base_url" },
        { status: 422 }
      )
    const conn: S["ConnectionOut"] = {
      id: uid(),
      created_at: now(),
      updated_at: now(),
      provider: body.provider,
      label: body.label,
      config: body.config ?? {},
      secrets_masked: Object.fromEntries(
        Object.entries(body.secrets ?? {}).map(([k, v]) => [k, mask(v)])
      ),
      scopes_granted: [],
      reads_description:
        "Sends prompts built by Nchito; reads nothing from your account.",
      health: "unknown",
      last_checked_at: null,
      enabled: true,
    }
    state.connections.push(conn)
    return HttpResponse.json(conn, { status: 201 })
  }),
  http.put("*/api/connections/:id", async ({ params, request }) => {
    const conn = state.connections.find((c) => c.id === params.id)
    if (!conn)
      return HttpResponse.json(
        { detail: "connection not found" },
        { status: 404 }
      )
    const body = (await request.json()) as S["ConnectionUpdate"]
    if (body.label) conn.label = body.label
    if (body.enabled !== undefined && body.enabled !== null)
      conn.enabled = body.enabled
    if (body.config) conn.config = body.config
    for (const [k, v] of Object.entries(body.secrets ?? {}))
      if (v) conn.secrets_masked[k] = mask(v)
    return HttpResponse.json(conn)
  }),
  http.delete("*/api/connections/:id", ({ params }) => {
    state.connections = state.connections.filter((c) => c.id !== params.id)
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/connections/:id/test", ({ params }) => {
    const conn = state.connections.find((c) => c.id === params.id)
    if (!conn)
      return HttpResponse.json(
        { detail: "connection not found" },
        { status: 404 }
      )
    conn.last_checked_at = now()
    if (state.settings["budget.monthly_cap_micros"] === null) {
      conn.health = "unknown"
      return HttpResponse.json({
        ok: false,
        detail: "Set a monthly cap first: paid calls stay off without one.",
        cost_minor: 0,
      })
    }
    conn.health = "ok"
    return HttpResponse.json({
      ok: true,
      detail: "Replied as expected.",
      cost_minor: 1,
    })
  }),

  http.get("*/api/ai/routing", () => HttpResponse.json(routes())),
  http.post("*/api/ai/routing/test", async ({ request }) => {
    const body = (await request.json()) as S["RouteTestIn"]
    const route = routes().find((r) => r.stage === body.stage)
    const model = body.model || route?.model || ""
    const provider = String(state.settings["ai.provider"])
    const ok =
      state.settings["budget.monthly_cap_micros"] !== null &&
      state.connections.length > 0
    state.tested[`${provider}/${model}`] = { ok, at: now() }
    return HttpResponse.json({
      ok,
      stage: body.stage,
      provider,
      model,
      detail: ok
        ? "Replied as expected."
        : state.connections.length === 0
          ? "no enabled anthropic provider: add one in Settings > AI"
          : "Set a monthly cap first: paid calls stay off without one.",
      cost_micros: ok ? 4_200 : 0,
      currency: "USD",
      billed: true,
      latency_ms: ok ? 840 : null,
    } satisfies S["RouteTestOut"])
  }),
  http.post("*/api/ai/routing/activate", async ({ request }) => {
    const body = (await request.json()) as S["RouteActivateIn"]
    const provider = String(state.settings["ai.provider"])
    if (!state.tested[`${provider}/${body.model}`]?.ok)
      return HttpResponse.json(
        {
          detail: `Test ${provider}/${body.model} successfully before activating it.`,
        },
        { status: 409 }
      )
    const key = STAGES.find(([s]) => s === body.stage)?.[1]
    if (key) state.settings[key] = body.model
    return HttpResponse.json(routes().find((r) => r.stage === body.stage))
  }),

  http.get("*/api/ai/prices", () => HttpResponse.json(state.prices)),
  http.put("*/api/ai/prices", async ({ request }) => {
    const body = (await request.json()) as S["PriceTableIn"]
    state.prices = body.prices.map((p) => ({
      ...p,
      input_per_mtok: String(p.input_per_mtok),
      output_per_mtok: String(p.output_per_mtok),
      cache_write_per_mtok:
        p.cache_write_per_mtok == null ? null : String(p.cache_write_per_mtok),
      cache_read_per_mtok:
        p.cache_read_per_mtok == null ? null : String(p.cache_read_per_mtok),
      long_context_threshold: p.long_context_threshold ?? null,
      long_input_per_mtok:
        p.long_input_per_mtok == null ? null : String(p.long_input_per_mtok),
      long_output_per_mtok:
        p.long_output_per_mtok == null ? null : String(p.long_output_per_mtok),
      source: p.source ?? null,
      id: uid(),
      updated_at: now(),
    }))
    return HttpResponse.json(state.prices)
  }),
  http.post("*/api/ai/prices/reset", () => {
    state.prices = seed().prices
    return HttpResponse.json(state.prices)
  }),

  http.get("*/api/ai/spend", () => {
    syncSpend()
    return HttpResponse.json(state.spend)
  }),
  http.get("*/api/ai/spend/meter", () => {
    syncSpend()
    const s = state.spend
    return HttpResponse.json({
      month_to_date_minor: s.month_to_date_minor,
      reserved_minor: s.reserved_minor,
      cap_minor: s.cap_minor,
      currency: s.currency,
      estimated_unbilled_minor: s.estimated_unbilled_minor,
      month_to_date_micros: s.month_to_date_micros,
      reserved_micros: s.reserved_micros,
      cap_micros: s.cap_micros,
      estimated_unbilled_micros: s.estimated_unbilled_micros,
    } satisfies S["SpendMeter"])
  }),

  http.get("*/api/kit/prompts", () =>
    HttpResponse.json(
      [...state.prompts].sort(
        (a, b) => a.stage.localeCompare(b.stage) || b.version - a.version
      )
    )
  ),
  http.post("*/api/kit/prompts", async ({ request }) => {
    const body = (await request.json()) as S["PromptIn"]
    const version =
      Math.max(
        0,
        ...state.prompts
          .filter((p) => p.stage === body.stage)
          .map((p) => p.version)
      ) + 1
    const prompt: S["PromptOut"] = {
      id: uid(),
      stage: body.stage,
      text: body.text,
      note: body.note ?? null,
      version,
      active: false,
      created_at: now(),
      updated_at: now(),
    }
    state.prompts.push(prompt)
    return HttpResponse.json(prompt, { status: 201 })
  }),
  http.post("*/api/kit/prompts/:id/activate", ({ params }) => {
    const prompt = state.prompts.find((p) => p.id === params.id)
    if (!prompt)
      return HttpResponse.json({ detail: "prompt not found" }, { status: 404 })
    for (const p of state.prompts)
      if (p.stage === prompt.stage) p.active = false
    prompt.active = true
    return HttpResponse.json(prompt)
  }),
]
