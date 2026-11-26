/**
 * Which document templates exist and which one applies. The renderer's built-ins are data in
 * `app/docs/layouts.py` (CONTRACTS, wave 2 render) and no endpoint lists them, so their keys
 * mirror the contract here. A Kit template row with the same key renames or overrides one; a row
 * with a new key adds one. The default is the track's choice, else the `documents.*_template`
 * setting, else the first built-in.
 */
import type { RenderKind, TemplateOut } from "./api"

export type TemplateOption = { key: string; name: string; pages: number | null }

const BUILT_IN: Record<RenderKind, { key: string; name: string }[]> = {
  cv: [
    { key: "classic", name: "Classic" },
    { key: "compact", name: "Compact" },
    { key: "modern", name: "Modern" },
  ],
  letter: [{ key: "letter-plain", name: "Plain letter" }],
}

export const SETTING_KEY: Record<RenderKind, string> = {
  cv: "documents.cv_template",
  letter: "documents.letter_template",
}

export function templateOptions(
  kind: RenderKind,
  rows: TemplateOut[]
): TemplateOption[] {
  const own = rows.filter((t) => t.kind === kind)
  const out: TemplateOption[] = BUILT_IN[kind].map((b) => {
    const row = own.find((t) => t.key === b.key)
    return {
      key: b.key,
      name: row?.name ?? b.name,
      pages: row?.limits?.pages ?? null,
    }
  })
  for (const t of own)
    if (!out.some((o) => o.key === t.key))
      out.push({ key: t.key, name: t.name, pages: t.limits?.pages ?? null })
  return out
}

export type TemplateSource = "track" | "setting" | "built-in"
export type DefaultTemplate = { key: string; source: TemplateSource }

/** The template that applies when the owner has not picked one here. */
export function defaultTemplate(
  kind: RenderKind,
  trackChoice: string | null | undefined,
  settingValue: unknown
): DefaultTemplate {
  if (trackChoice) return { key: trackChoice, source: "track" }
  if (typeof settingValue === "string" && settingValue)
    return { key: settingValue, source: "setting" }
  return { key: BUILT_IN[kind][0].key, source: "built-in" }
}

export const SOURCE_TEXT: Record<TemplateSource, string> = {
  track: "set by this role's track",
  setting: "your documents setting",
  "built-in": "the standard layout",
}
