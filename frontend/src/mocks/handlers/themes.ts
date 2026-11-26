/**
 * Mock backend for themes and the theme studio (CONTRACTS "Wave 4 themes additions"): built-ins
 * read-only, owner themes with revisions (undo/redo/restore), duplicate, default, contrast block
 * with recorded acceptance, strict import/export. Mirrors `backend/app/themes/service.py`.
 */
import { http, HttpResponse } from "msw"
import { BUILTIN_THEMES } from "@/themes"
import { evaluateContrast } from "@/themes/contrast"
import type { Theme } from "@/themes/schema"
import { themeIssues } from "@/themes/validate"
import type { Schemas } from "@/lib/api/types"
import { db, type MockThemeRevision } from "../db"
import { settingRow } from "../dataset/settings"

type ThemeOut = Schemas["ThemeOut"]
type Body = Omit<Theme, "id" | "builtin">

const BODY_KEYS = [
  "name",
  "description",
  "fonts",
  "radius",
  "density",
  "light",
  "dark",
  "chart",
  "score",
] as const
const OUT_ONLY = [
  "id",
  "builtin",
  "is_default",
  "revision",
  "can_undo",
  "can_redo",
  "contrast_waiver",
  "needs_review",
]

const unauthorized = () =>
  HttpResponse.json({ detail: "Not signed in." }, { status: 401 })
const err = (status: number, detail: unknown) =>
  HttpResponse.json({ detail }, { status })
const signedIn = () => db.get().session

const waivers = new Map<string, ThemeOut["contrast_waiver"]>()

function bodyOf(t: Theme | Body): Body {
  const out: Record<string, unknown> = {}
  for (const k of BODY_KEYS)
    if (k in t && (t as Record<string, unknown>)[k] !== undefined)
      out[k] = (t as Record<string, unknown>)[k]
  return out as Body
}

function revs(id: string): MockThemeRevision[] {
  return db.get().themeRevisions[id] ?? []
}

function toOut(t: Theme): ThemeOut {
  const s = db.get()
  const current = s.themeCurrent[t.id] ?? null
  const list = revs(t.id)
  const cur = list.find((r) => r.number === current)
  return {
    ...t,
    description: t.description ?? null,
    is_default: s.defaultThemeId === t.id,
    revision: t.builtin ? null : current,
    can_undo:
      !!cur && cur.parent !== null && list.some((r) => r.number === cur.parent),
    can_redo: list.some((r) => r.parent === current),
    contrast_waiver: waivers.get(t.id) ?? null,
    needs_review: !waivers.get(t.id) && !!t.needs_review,
  } as ThemeOut
}

const all = (): Theme[] => [...BUILTIN_THEMES, ...db.get().customThemes]
const find = (id: string) => all().find((t) => t.id === id)

function validate(raw: Record<string, unknown>): {
  body?: Body
  error?: string
} {
  const extra = Object.keys(raw).filter(
    (k) => !(BODY_KEYS as readonly string[]).includes(k)
  )
  if (extra.length)
    return { error: `${extra[0]}: Extra inputs are not permitted` }
  const body = raw as unknown as Body
  if (!body.light || !body.dark || !body.fonts || !body.chart || !body.score)
    return { error: "Field required" }
  const issues = themeIssues({ ...body, fonts: { ...body.fonts } })
  return issues.length
    ? { error: `${issues[0].path}: ${issues[0].message}` }
    : { body }
}

function blocking(body: Body) {
  return [
    ...evaluateContrast(body.light, "light", body.chart, body.score),
    ...evaluateContrast(body.dark, "dark", body.chart, body.score),
  ].filter((r) => r.blocking)
}

function contrastGate(id: string | null, body: Body, accept: boolean) {
  const fails = blocking(body)
  if (!fails.length) {
    if (id) waivers.delete(id)
    return null
  }
  if (!accept)
    return err(422, {
      code: "theme_low_contrast",
      reason:
        "Body text is below WCAG AA contrast. Fix the colours, or accept it for this personal theme.",
      pairs: fails.map(({ mode, fg, bg, ratio }) => ({ mode, fg, bg, ratio })),
    })
  return fails
}

function record(id: string, body: Body, note: string) {
  db.update((s) => {
    const list = (s.themeRevisions[id] ??= [])
    const number = (list[list.length - 1]?.number ?? 0) + 1
    list.push({
      number,
      parent: s.themeCurrent[id] ?? null,
      note,
      actor: "owner",
      created_at: new Date().toISOString(),
      body,
    })
    s.themeCurrent[id] = number
    const keep = Number(
      settingRow("themes.revisions_kept")?.value ?? list.length
    )
    s.themeRevisions[id] = list.filter((r) => r.number > number - keep)
  })
}

function freeName(wanted: string) {
  const names = new Set(all().map((t) => t.name))
  if (!names.has(wanted)) return wanted
  for (let i = 2; ; i++)
    if (!names.has(`${wanted} (${i})`)) return `${wanted} (${i})`
}

function create(
  body: Body,
  note: string,
  fails: ReturnType<typeof blocking> | null,
  slug?: string | null
) {
  const id = slug ?? crypto.randomUUID()
  const theme = { ...body, id, builtin: false } as Theme
  db.update((s) => {
    s.customThemes.push(theme)
  })
  if (fails)
    waivers.set(id, {
      pairs: fails.map(({ mode, fg, bg, ratio }) => ({ mode, fg, bg, ratio })),
      accepted_at: new Date().toISOString(),
      accepted_by: "owner",
    })
  record(id, body, note)
  return theme
}

function moveTo(id: string, number: number | null | undefined) {
  if (BUILTIN_THEMES.some((t) => t.id === id))
    return err(403, "Built-in themes have no revisions.")
  const rev = revs(id).find((r) => r.number === number)
  if (!rev) return err(409, "Nothing to go back or forward to.")
  db.update((s) => {
    const i = s.customThemes.findIndex((t) => t.id === id)
    s.customThemes[i] = { ...rev.body, id, builtin: false } as Theme
    s.themeCurrent[id] = rev.number
  })
  return HttpResponse.json(toOut(find(id)!))
}

export const themesHandlers = [
  http.get("*/api/themes", () => {
    if (!signedIn()) return unauthorized()
    return HttpResponse.json(all().map(toOut))
  }),
  http.post("*/api/themes/import", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const limit = Number(settingRow("themes.import_max_bytes")?.value)
    const raw = await request.text()
    if (new TextEncoder().encode(raw).length > limit)
      return err(413, `theme file is larger than ${limit} bytes`)
    let data: unknown
    try {
      data = JSON.parse(raw)
    } catch {
      return err(422, { code: "invalid_theme_file", reason: "not a JSON file" })
    }
    if (!data || typeof data !== "object" || Array.isArray(data))
      return err(422, {
        code: "invalid_theme_file",
        reason: "a theme file is a JSON object",
      })
    const obj = data as Record<string, unknown>
    const candidate =
      obj.format === "nchito-theme"
        ? (obj.theme as Record<string, unknown>)
        : Object.fromEntries(
            Object.entries(obj).filter(([k]) => !OUT_ONLY.includes(k))
          )
    const { body, error } = validate(candidate ?? {})
    if (!body) return err(422, { code: "invalid_theme_file", reason: error })
    const accept =
      new URL(request.url).searchParams.get("accept_low_contrast") === "true"
    const gate = contrastGate(null, body, accept)
    if (gate instanceof Response) return gate
    const theme = create(
      { ...body, name: freeName(body.name) },
      "Imported",
      gate
    )
    return HttpResponse.json(toOut(theme), { status: 201 })
  }),
  http.post("*/api/themes/contrast", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const body = (await request.json()) as Body
    return HttpResponse.json([
      ...evaluateContrast(body.light, "light", body.chart, body.score),
      ...evaluateContrast(body.dark, "dark", body.chart, body.score),
    ])
  }),
  http.get("*/api/themes/:id", ({ params }) => {
    const t = find(String(params.id))
    return t ? HttpResponse.json(toOut(t)) : err(404, "theme not found")
  }),
  http.post("*/api/themes", async ({ request }) => {
    if (!signedIn()) return unauthorized()
    const { id, accept_low_contrast, ...rest } =
      (await request.json()) as Record<string, unknown>
    const { body, error } = validate(rest)
    if (!body) return err(422, error)
    if (id && find(String(id)))
      return err(409, `theme id '${String(id)}' is taken`)
    const gate = contrastGate(null, body, accept_low_contrast === true)
    if (gate instanceof Response) return gate
    return HttpResponse.json(
      toOut(create(body, "Created", gate, id ? String(id) : null)),
      { status: 201 }
    )
  }),
  http.put("*/api/themes/:id/default", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const t = find(String(params.id))
    if (!t) return err(404, "theme not found")
    db.update((s) => {
      s.defaultThemeId = t.id
    })
    return HttpResponse.json(toOut(t))
  }),
  http.put("*/api/themes/:id", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const id = String(params.id)
    const t = find(id)
    if (!t) return err(404, "theme not found")
    if (t.builtin)
      return err(403, "built-in themes are read-only; duplicate it instead")
    const {
      id: _ignored,
      accept_low_contrast,
      ...rest
    } = (await request.json()) as Record<string, unknown>
    void _ignored
    const { body, error } = validate(rest)
    if (!body) return err(422, error)
    const gate = contrastGate(id, body, accept_low_contrast === true)
    if (gate instanceof Response) return gate
    if (gate)
      waivers.set(id, {
        pairs: gate.map(({ mode, fg, bg, ratio }) => ({ mode, fg, bg, ratio })),
        accepted_at: new Date().toISOString(),
        accepted_by: "owner",
      })
    const renamed = body.name !== t.name
    db.update((s) => {
      const i = s.customThemes.findIndex((x) => x.id === id)
      s.customThemes[i] = { ...body, id, builtin: false } as Theme
    })
    record(id, body, renamed ? "Renamed" : "Saved")
    return HttpResponse.json(toOut(find(id)!))
  }),
  http.delete("*/api/themes/:id", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const id = String(params.id)
    const t = find(id)
    if (!t) return err(404, "theme not found")
    if (t.builtin) return err(403, "built-in themes cannot be deleted")
    if (db.get().appearance.theme_id === id)
      return err(409, "this theme is in use; switch to another theme first")
    if (db.get().defaultThemeId === id)
      return err(
        409,
        "this is the default theme; make another theme the default first"
      )
    db.update((s) => {
      s.customThemes = s.customThemes.filter((x) => x.id !== id)
      delete s.themeRevisions[id]
      delete s.themeCurrent[id]
    })
    return new HttpResponse(null, { status: 204 })
  }),
  http.post("*/api/themes/:id/duplicate", async ({ params, request }) => {
    if (!signedIn()) return unauthorized()
    const src = find(String(params.id))
    if (!src) return err(404, "theme not found")
    const { name } = ((await request.json().catch(() => ({}))) ?? {}) as {
      name?: string | null
    }
    const theme = create(
      { ...bodyOf(src), name: freeName(name || `${src.name} copy`) },
      `Duplicated from ${src.name}`,
      null
    )
    return HttpResponse.json(toOut(theme), { status: 201 })
  }),
  http.get("*/api/themes/:id/export", ({ params }) => {
    const t = find(String(params.id))
    if (!t) return err(404, "theme not found")
    return HttpResponse.json({
      format: "nchito-theme",
      version: 1,
      theme: { ...bodyOf(t), description: t.description ?? null },
    })
  }),
  http.get("*/api/themes/:id/revisions", ({ params }) => {
    const id = String(params.id)
    const current = db.get().themeCurrent[id]
    return HttpResponse.json(
      [...revs(id)]
        .reverse()
        .map((r) => ({ ...r, current: r.number === current }))
    )
  }),
  http.post("*/api/themes/:id/undo", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const id = String(params.id)
    const cur = revs(id).find((r) => r.number === db.get().themeCurrent[id])
    return moveTo(id, cur?.parent)
  }),
  http.post("*/api/themes/:id/redo", ({ params }) => {
    if (!signedIn()) return unauthorized()
    const id = String(params.id)
    const child = [...revs(id)]
      .reverse()
      .find((r) => r.parent === db.get().themeCurrent[id])
    return moveTo(id, child?.number)
  }),
  http.post("*/api/themes/:id/revisions/:n/restore", ({ params }) => {
    if (!signedIn()) return unauthorized()
    return moveTo(String(params.id), Number(params.n))
  }),
]
