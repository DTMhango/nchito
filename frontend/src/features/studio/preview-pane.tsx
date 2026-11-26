import type { MouseEvent, ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { PaperPage, PaperPreview } from "@/components/paper-preview"
import type { DocFormat, ExperienceOut, RenderKind, TemplateOut } from "./api"
import { documentUrl, renderQuery } from "./api"
import type { Draft, ScreeningRow } from "./draft"
import { needsOwner } from "./draft"
import { SOURCE_TEXT, templateOptions, type DefaultTemplate } from "./templates"

export type PreviewDoc = "cv" | "letter" | "answers"

const SELECT =
  "h-8 rounded-md border border-input bg-surface px-2 text-sm field-focus"

const year = (d: string | null | undefined) => (d ? d.slice(0, 4) : null)

function CvPages({
  draft,
  template,
  owner,
  experiences,
}: {
  draft: Draft
  template: TemplateOut | undefined
  owner: string
  experiences: ExperienceOut[]
}) {
  const sections: Record<string, ReactNode> = {
    summary: (draft.summary?.text || draft.competencies.length > 0) && (
      <div key="summary">
        <h4>Summary</h4>
        {draft.summary?.text && <p>{draft.summary.text}</p>}
        {draft.competencies.length > 0 && (
          <ul>
            {draft.competencies.map((c) => (
              <li key={c.key}>{c.text}</li>
            ))}
          </ul>
        )}
      </div>
    ),
    experience: draft.experience.length > 0 && (
      <div key="experience">
        <h4>Experience</h4>
        {draft.experience.map((e) => {
          const x = experiences.find((k) => k.id === e.experience_id)
          const from = year(x?.start_date)
          const to = x ? (year(x.end_date) ?? "now") : null
          return (
            <div key={e.key} className="mt-[1.6cqw]">
              <div className="flex justify-between gap-[2cqw] font-semibold">
                {e.title ?? "Role"}
                {from && (
                  <span className="font-normal whitespace-nowrap text-paper-muted">
                    {from} to {to}
                  </span>
                )}
              </div>
              {x && (
                <div className="text-paper-muted">
                  {[x.org, x.location].filter(Boolean).join(", ")}
                </div>
              )}
              <ul>
                {e.bullets
                  .filter((b) => b.text.trim())
                  .map((b) => (
                    <li key={b.key}>{b.text}</li>
                  ))}
              </ul>
            </div>
          )
        })}
      </div>
    ),
    skills: draft.skills.length > 0 && (
      <div key="skills">
        <h4>Skills</h4>
        <p>{draft.skills.join(", ")}.</p>
      </div>
    ),
  }
  const order = [
    ...(template?.section_order ?? []).filter((s) => s in sections),
    ...Object.keys(sections).filter(
      (s) => !(template?.section_order ?? []).includes(s)
    ),
  ]
  return (
    <PaperPage variant="cv" className="!aspect-auto">
      <h3>{owner}</h3>
      {draft.headline?.text && (
        <div className="mt-[0.5cqw] text-[2cqw] text-paper-muted">
          {draft.headline.text}
        </div>
      )}
      {order.map((s) => sections[s])}
    </PaperPage>
  )
}

function LetterPage({ draft, owner }: { draft: Draft; owner: string }) {
  return (
    <PaperPage variant="letter" className="!aspect-auto">
      {draft.letter
        .filter((p) => p.text.trim())
        .map((p) => (
          <p key={p.key}>{p.text}</p>
        ))}
      <p>{owner}</p>
    </PaperPage>
  )
}

function AnswersPage({ rows }: { rows: ScreeningRow[] }) {
  return (
    <PaperPage variant="cv" className="!aspect-auto">
      <h4 className="!mt-0">Application questions · {rows.length}</h4>
      {rows.map((r) => (
        <div
          key={r.question}
          className="grid gap-[0.6cqw] border-b border-paper-rule py-[2cqw]"
        >
          <b className="font-semibold">{r.question}</b>
          <span className="text-paper-muted">
            {r.standing.kind === "value"
              ? r.standing.value
              : r.standing.kind === "declined"
                ? (r.standing.select ?? "Left unanswered")
                : "Waiting for your answer"}
          </span>
        </div>
      ))}
    </PaperPage>
  )
}

/** The renderer's warnings for the saved version in this template (never computed here). */
function RenderWarnings({
  applicationId,
  kind,
  template,
  contentHash,
}: {
  applicationId: string
  kind: RenderKind
  template: string
  contentHash: string | null
}) {
  const out = useQuery(renderQuery(applicationId, kind, template, contentHash))
  if (out.isError)
    return (
      <p role="alert" className="text-sm text-danger">
        Could not lay out this document: {out.error.message}
      </p>
    )
  const warnings = out.data?.warnings ?? []
  if (warnings.length === 0) return null
  return (
    <ul className="m-0 grid list-none gap-1 p-0" aria-label="Layout warnings">
      {warnings.map((w) => (
        <li
          key={`${w.code}-${w.message}`}
          data-code={w.code}
          className="flex items-start gap-2 rounded-sm bg-warn-soft px-2.5 py-1.5 text-sm text-warn"
        >
          <AlertTriangle
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0"
          />
          {w.message}
        </li>
      ))}
    </ul>
  )
}

const FORMATS: DocFormat[] = ["pdf", "docx", "txt"]

/** Live preview on white paper, the template for each document, and the rendered files. */
export function PreviewPane({
  doc,
  draft,
  owner,
  experiences,
  kitTemplates,
  chosen,
  defaults,
  onTemplate,
  answers,
  applicationId,
  contentHash,
  beforeDownload,
  saving,
}: {
  doc: PreviewDoc
  draft: Draft
  owner: string
  experiences: ExperienceOut[]
  kitTemplates: TemplateOut[]
  /** The template picked here for each document (the default applies until one is picked). */
  chosen: Record<RenderKind, string>
  defaults: Record<RenderKind, DefaultTemplate>
  onTemplate: (kind: RenderKind, key: string) => void
  answers: ScreeningRow[]
  applicationId: string
  /** The saved spec version the server renders from; null before the first version. */
  contentHash: string | null
  beforeDownload: () => Promise<void>
  saving: boolean
}) {
  const kind = doc === "answers" ? null : doc
  const options = kind ? templateOptions(kind, kitTemplates) : []
  const key = kind ? chosen[kind] : undefined
  const option = options.find((t) => t.key === key)
  const row = kind
    ? kitTemplates.find((t) => t.kind === kind && t.key === key)
    : undefined
  const open = answers.filter(needsOwner).length

  const download = (fmt: DocFormat) => async (e: MouseEvent) => {
    e.preventDefault()
    await beforeDownload()
    window.location.assign(documentUrl(applicationId, doc, fmt, key))
  }

  return (
    <section aria-label="Preview" className="grid min-w-0 gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        {kind ? (
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            Template
            <select
              className={SELECT}
              value={key}
              onChange={(e) => onTemplate(kind, e.target.value)}
            >
              {options.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.name}
                  {t.key === defaults[kind].key ? " (default)" : ""}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="text-sm text-muted-foreground">
            {`${answers.length} question${answers.length === 1 ? "" : "s"}${open ? ` · ${open} need${open === 1 ? "s" : ""} you` : ""}`}
          </span>
        )}
        <span className="ml-auto num text-xs text-faint">
          A4
          {option?.pages
            ? ` · limit ${option.pages} page${option.pages === 1 ? "" : "s"}`
            : ""}
        </span>
      </div>
      {kind && (
        <p className="text-xs text-faint" data-testid="template-source">
          Default:{" "}
          {options.find((t) => t.key === defaults[kind].key)?.name ??
            defaults[kind].key}
          , {SOURCE_TEXT[defaults[kind].source]}.
        </p>
      )}

      {kind && key && !saving && (
        <RenderWarnings
          applicationId={applicationId}
          kind={kind}
          template={key}
          contentHash={contentHash}
        />
      )}

      <PaperPreview
        label={
          doc === "cv"
            ? "CV preview"
            : doc === "letter"
              ? "Cover letter preview"
              : "Answers preview"
        }
      >
        {doc === "cv" && (
          <CvPages
            draft={draft}
            template={row}
            owner={owner}
            experiences={experiences}
          />
        )}
        {doc === "letter" && <LetterPage draft={draft} owner={owner} />}
        {doc === "answers" && <AnswersPage rows={answers} />}
      </PaperPreview>

      <div className="flex flex-wrap items-center gap-2">
        {(doc === "answers" ? (["txt"] as DocFormat[]) : FORMATS).map((fmt) => (
          <Button key={fmt} asChild size="sm" variant="outline">
            <a
              href={documentUrl(applicationId, doc, fmt, key)}
              onClick={download(fmt)}
              aria-disabled={saving}
            >
              <Download aria-hidden="true" />
              {fmt.toUpperCase()}
            </a>
          </Button>
        ))}
        <span className="text-xs text-faint">
          {saving
            ? "Saving first, then downloading"
            : "Rendered from the last saved version"}
        </span>
      </div>
    </section>
  )
}
