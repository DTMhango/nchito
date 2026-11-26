/**
 * The discovery connectors added in wave 3 (JobSpy, careers pages, web search): their config
 * keys, exactly as the backend connectors read them (`backend/app/sources/jobspy.py`,
 * `careers_page.py`, `web_search.py`), and the pure helpers the forms use.
 *
 * Every number a source may override comes from the `sources.*` settings registry: a blank
 * override means "use the setting", and limits are the setting's own minimum and maximum. No
 * default lives here.
 */
import type { components } from "@/lib/api/types"
import type { Source } from "./api"

type SettingOut = components["schemas"]["SettingOut"]
type Connection = components["schemas"]["ConnectionOut"]

export const NEW_CONNECTORS = ["jobspy", "careers_page", "web_search"] as const
export type NewConnector = (typeof NEW_CONNECTORS)[number]

export const isNewConnector = (c: string): c is NewConnector =>
  (NEW_CONNECTORS as readonly string[]).includes(c)

/** How each connector reads (the backend refuses any other `access`). */
export const CONNECTOR_ACCESS: Record<NewConnector, Source["access"]> = {
  jobspy: "html",
  careers_page: "html",
  web_search: "api",
}

export const CONNECTOR_INFO: Record<
  NewConnector,
  { label: string; blurb: string }
> = {
  jobspy: {
    label: "JobSpy boards",
    blurb:
      "LinkedIn, Indeed, Glassdoor and Google Jobs through the optional JobSpy library. Best effort and discovery only: it never applies.",
  },
  careers_page: {
    label: "Careers pages",
    blurb:
      "Employers with no job board API. Each careers page is read politely (robots.txt is always honoured).",
  },
  web_search: {
    label: "Web search",
    blurb:
      "Searches the web for your campaign titles. Results are leads only: a result is kept only when its page holds a real posting.",
  },
}

/** The settings group every connector setting lives in, and each connector's key prefix. */
export const SOURCES_GROUP = "sources"
export const SETTING_PREFIX: Record<NewConnector, string> = {
  jobspy: "sources.jobspy.",
  careers_page: "sources.careers.",
  web_search: "sources.search.",
}
/** The global switch for JobSpy (off by default in the registry). */
export const JOBSPY_ENABLED_KEY = "sources.jobspy.enabled"

/**
 * Per-source overrides: the source config key is the last word of the setting key (the backend's
 * `knob()`), so a source may narrow or widen what the setting says.
 */
export const OVERRIDES: Record<NewConnector, readonly string[]> = {
  jobspy: [
    "boards",
    "results_per_board",
    "board_delay_seconds",
    "max_age_hours",
    "verify_links",
  ],
  careers_page: [
    "max_postings",
    "max_detail_pages",
    "llm_extraction",
    "llm_max_cost_micros",
  ],
  web_search: [
    "max_queries",
    "results_per_query",
    "max_leads",
    "query_template",
  ],
}

export const settingKey = (kind: NewConnector, name: string) =>
  `${SETTING_PREFIX[kind]}${name}`

/**
 * The provider fields of a Search API connection (search_api `CONFIG_KEYS`). They live on the
 * connection only: a web search source never carries them (the server drops them), so a form
 * removes any an older source still has.
 */
export const SEARCH_SHAPE_KEYS = [
  "endpoint",
  "query_param",
  "limit_param",
  "key_header",
  "key_param",
  "result_path",
  "url_field",
  "title_field",
] as const

export const SEARCH_PROVIDER = "search_api"

// ---- errors ------------------------------------------------------------------------------

/** The backend says "JobSpy is not installed on this server" (create 422, test, run error). */
export const isNotInstalled = (text: string | null | undefined) =>
  !!text && /not installed/i.test(text)
/** "JobSpy is switched off (setting sources.jobspy.enabled)". */
export const isSwitchedOff = (text: string | null | undefined) =>
  !!text && /switched off/i.test(text)
/** The extra the backend names in its "not installed" message. */
export const JOBSPY_INSTALL = "pip install 'nchito[jobspy]'"

// ---- drafts --------------------------------------------------------------------------------

export type EmployerRow = { url: string; name: string }

/** What the forms edit. Override values are strings ("" = use the setting) or a list. */
export type Draft = {
  overrides: Record<string, string | string[]>
  employers: EmployerRow[]
  /** Web search: "" = the first enabled Search API connection (as the backend does). */
  connectionId: string
  /** JobSpy: explicit search phrases, one per line ("" = the campaign's titles). */
  queries: string
}

export const emptyDraft = (): Draft => ({
  overrides: {},
  employers: [{ url: "", name: "" }],
  connectionId: "",
  queries: "",
})

export function draftFromConfig(
  kind: NewConnector,
  config: Record<string, unknown> | undefined
): Draft {
  const c = config ?? {}
  const overrides: Draft["overrides"] = {}
  for (const name of OVERRIDES[kind]) {
    const v = c[name]
    if (v == null) continue
    overrides[name] = Array.isArray(v) ? v.map(String) : String(v)
  }
  const raw = c.employers ?? c.urls
  const list = Array.isArray(raw) ? raw : typeof raw === "string" ? [raw] : []
  const employers = list.map((e) =>
    typeof e === "string"
      ? { url: e, name: "" }
      : {
          url: String((e as { url?: unknown }).url ?? ""),
          name: String((e as { name?: unknown }).name ?? ""),
        }
  )
  return {
    overrides,
    employers: employers.length ? employers : [{ url: "", name: "" }],
    connectionId: typeof c.connection_id === "string" ? c.connection_id : "",
    queries: Array.isArray(c.queries) ? c.queries.map(String).join("\n") : "",
  }
}

const isHttpUrl = (s: string) => {
  try {
    const u = new URL(s.trim())
    return (u.protocol === "http:" || u.protocol === "https:") && !!u.host
  } catch {
    return false
  }
}

/** The Search API connection a web search source uses: its own, else the first enabled one. */
export function searchConnectionFor(
  connectionId: string,
  connections: readonly Connection[]
): Connection | null {
  const search = connections.filter((c) => c.provider === SEARCH_PROVIDER)
  if (connectionId) {
    const own = search.find((c) => c.id === connectionId)
    return own && own.enabled ? own : null
  }
  return (
    [...search]
      .filter((c) => c.enabled)
      .sort((a, b) => a.created_at.localeCompare(b.created_at))[0] ?? null
  )
}

/** Check one override against its registry definition; returns the value to store or an error. */
export function parseOverride(
  setting: SettingOut | undefined,
  raw: string | string[]
): { ok: true; value: unknown } | { ok: false; error: string } {
  const label = setting?.label ?? "This value"
  if (Array.isArray(raw)) {
    const bad = raw.find(
      (v) => setting?.choices && !setting.choices.includes(v)
    )
    if (bad) return { ok: false, error: `${label}: ${bad} is not offered.` }
    return { ok: true, value: raw }
  }
  const text = raw.trim()
  const kind = setting?.kind ?? "string"
  if (kind === "bool") return { ok: true, value: text === "true" }
  if (kind === "int" || kind === "float" || kind === "money_minor") {
    const n = Number(text)
    if (!Number.isFinite(n) || (kind !== "float" && !Number.isInteger(n)))
      return { ok: false, error: `${label} must be a whole number.` }
    if (setting?.minimum != null && n < setting.minimum)
      return {
        ok: false,
        error: `${label} must be at least ${setting.minimum}.`,
      }
    if (setting?.maximum != null && n > setting.maximum)
      return {
        ok: false,
        error: `${label} must be at most ${setting.maximum}.`,
      }
    return { ok: true, value: n }
  }
  if (setting?.key.endsWith(".query_template") && !text.includes("{title}"))
    return { ok: false, error: `${label} must contain {title}.` }
  return { ok: true, value: text }
}

/**
 * Turn a draft into the source config the backend validates, or a plain-words problem.
 * `base` keeps keys this form does not edit.
 */
export function buildConfig(
  kind: NewConnector,
  draft: Draft,
  settings: readonly SettingOut[],
  connections: readonly Connection[],
  base: Record<string, unknown> = {}
):
  { ok: true; config: Record<string, unknown> } | { ok: false; error: string } {
  const config: Record<string, unknown> = { ...base }
  for (const name of OVERRIDES[kind]) {
    const raw = draft.overrides[name]
    const empty =
      raw == null || (Array.isArray(raw) ? !raw.length : !raw.trim())
    if (empty) {
      delete config[name]
      continue
    }
    const parsed = parseOverride(
      settings.find((s) => s.key === settingKey(kind, name)),
      raw
    )
    if (!parsed.ok) return parsed
    config[name] = parsed.value
  }

  if (kind === "jobspy") {
    const queries = draft.queries
      .split("\n")
      .map((q) => q.trim())
      .filter(Boolean)
    if (queries.length) config.queries = queries
    else delete config.queries
  }

  if (kind === "careers_page") {
    const rows = draft.employers.filter((e) => e.url.trim() || e.name.trim())
    if (!rows.length)
      return { ok: false, error: "Add at least one careers page link." }
    const bad = rows.find((e) => !isHttpUrl(e.url))
    if (bad)
      return {
        ok: false,
        error: `${bad.url.trim() || "A link"} is not a web address (http or https).`,
      }
    config.employers = rows.map((e) =>
      e.name.trim()
        ? { url: e.url.trim(), name: e.name.trim() }
        : { url: e.url.trim() }
    )
    delete config.urls
  }

  if (kind === "web_search") {
    const conn = searchConnectionFor(draft.connectionId, connections)
    if (!conn)
      return {
        ok: false,
        error: draft.connectionId
          ? "That Search API connection is paused or gone. Choose another."
          : "Add a Search API connection first (Settings, Connections).",
      }
    // The endpoint, response shape and key belong to the connection only; never to the source.
    for (const k of SEARCH_SHAPE_KEYS) delete config[k]
    if (draft.connectionId) config.connection_id = draft.connectionId
    else delete config.connection_id
  }
  return { ok: true, config }
}

/** The setting's current value in words, for "Leave empty to use ..." hints. */
export function settingValueText(s: SettingOut | undefined): string {
  if (!s) return "the setting"
  const v = s.value
  if (typeof v === "boolean") return v ? "on" : "off"
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none"
  if (v == null) return "not set"
  return s.unit ? `${String(v)} ${s.unit}` : String(v)
}
