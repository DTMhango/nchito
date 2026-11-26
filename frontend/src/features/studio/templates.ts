/**
 * Which document templates exist and which one applies, as the server reports them
 * (`GET /api/document-templates?application_id=`): built-ins in shipped order, then the owner's
 * Kit templates, with effective limits and the default per kind (the track's choice, else the
 * documents setting). The frontend keeps no list of its own.
 */
import type { DocumentTemplates, RenderKind, TemplateOption } from "./api"

export type TemplateSource = DocumentTemplates["defaults"][string]["source"]
export type DefaultTemplate = { key: string; source: TemplateSource | null }

export const templateOptions = (
  kind: RenderKind,
  data: DocumentTemplates | undefined
): TemplateOption[] => (data?.templates ?? []).filter((t) => t.kind === kind)

/** The template that applies when the owner has not picked one here. */
export function defaultTemplate(
  kind: RenderKind,
  data: DocumentTemplates | undefined
): DefaultTemplate | null {
  const d = data?.defaults[kind]
  if (d) return { key: d.key, source: d.source }
  const first = templateOptions(kind, data)[0]
  return first ? { key: first.key, source: null } : null
}

export const SOURCE_TEXT: Record<TemplateSource, string> = {
  track: "set by this role's track",
  setting: "your documents setting",
}
