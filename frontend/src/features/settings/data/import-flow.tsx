import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { FileUp } from "lucide-react"
import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/chip"
import {
  commitImport,
  previewImport,
  type ImportCommit,
  type ImportDiffItem,
  type ImportPreview,
  type ImportSource,
} from "./api"
import { AiNotice, useSendsToAi } from "./ai-notice"

export const IMPORT_SOURCES: {
  value: ImportSource
  label: string
  hint: string
  accept: string
}[] = [
  {
    value: "kit_file",
    label: "A kit file or shareable template (.kit.zip)",
    hint: "A file made by Export here, or a template someone shared.",
    accept: ".zip",
  },
  {
    value: "old_kit_zip",
    label: "An old job-hunting folder (.zip)",
    hint: "Known files are read by code. Everything arrives unconfirmed.",
    accept: ".zip",
  },
  {
    value: "history_csv",
    label: "Application history (.csv)",
    hint: "Past applications, so you are not sent to the same job twice.",
    accept: ".csv",
  },
  {
    value: "free_form",
    label: "Notes or a CV as text (.txt, .md, .docx, .xlsx)",
    hint: "Your AI provider proposes facts from it. Everything arrives unconfirmed.",
    accept: ".txt,.md,.docx,.xlsx",
  },
]

/** The diff key the commit's `exclude_keys` expects. */
export const diffKey = (d: ImportDiffItem) => `${d.entity}:${d.key}`

/** What a change means in plain words. */
const CHANGE_LABEL: Record<ImportDiffItem["change"], string> = {
  add: "Will be added",
  update: "Will replace what you have",
  conflict: "Conflicts with what you have",
  unchanged: "Already the same",
}
const CHANGE_TONE = {
  add: "good",
  update: "info",
  conflict: "warn",
  unchanged: "neutral",
} as const

const show = (v: unknown) =>
  v === undefined || v === null
    ? "nothing"
    : typeof v === "string"
      ? v
      : JSON.stringify(v)

/**
 * Upload, preview, then confirm. The first call only reads the file and returns a diff; the
 * only call that writes is "Import", which cannot be pressed before a preview is on screen.
 */
export function ImportFlow({
  sources = IMPORT_SOURCES,
  initialSource,
  onDone,
}: {
  sources?: typeof IMPORT_SOURCES
  initialSource?: ImportSource
  onDone?: (r: ImportCommit, source: ImportSource) => void
}) {
  const qc = useQueryClient()
  const fileId = useId()
  const [source, setSource] = useState<ImportSource>(
    initialSource ?? sources[0].value
  )
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [skip, setSkip] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<ImportCommit | null>(null)
  const [aiOk, setAiOk] = useState(false)
  const sendsToAi = useSendsToAi(source)

  const read = useMutation({
    mutationFn: () => previewImport(file as File, source),
    onSuccess: (p) => {
      setPreview(p)
      setResult(null)
      // Conflicts start excluded: they replace nothing until you opt in.
      setSkip(
        new Set(
          p.diff
            .filter((d) => d.change === "conflict" || d.change === "unchanged")
            .map(diffKey)
        )
      )
    },
  })
  const write = useMutation({
    mutationFn: () =>
      commitImport((preview as ImportPreview).import_id, [...skip]),
    onSuccess: (r) => {
      setResult(r)
      setPreview(null)
      setFile(null)
      void qc.invalidateQueries({ queryKey: ["kit"] })
      void qc.invalidateQueries({ queryKey: ["onboarding"] })
      onDone?.(r, source)
    },
  })

  const chosen = sources.find((s) => s.value === source) ?? sources[0]
  const count = (c: ImportDiffItem["change"]) =>
    preview?.diff.filter((d) => d.change === c).length ?? 0
  const included =
    preview?.diff.filter(
      (d) => !skip.has(diffKey(d)) && d.change !== "unchanged"
    ).length ?? 0

  return (
    <div className="grid gap-4">
      {!preview && (
        <form
          aria-label="Choose a file to import"
          className="grid max-w-[60ch] gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (file && (!sendsToAi || aiOk)) read.mutate()
          }}
        >
          <fieldset className="grid gap-1.5">
            <legend className="font-semibold">What are you importing?</legend>
            {sources.map((s) => (
              <label key={s.value} className="flex items-start gap-2">
                <input
                  type="radio"
                  name="import-source"
                  checked={source === s.value}
                  onChange={() => {
                    setSource(s.value)
                    setAiOk(false)
                  }}
                  className="mt-1"
                />
                <span>{s.label}</span>
              </label>
            ))}
            <p className="text-sm text-muted-foreground">{chosen.hint}</p>
          </fieldset>
          {sendsToAi && (
            <AiNotice
              source={source}
              acknowledged={aiOk}
              onAcknowledge={setAiOk}
            />
          )}
          <div className="grid gap-1">
            <label htmlFor={fileId} className="font-semibold">
              File
            </label>
            <input
              id={fileId}
              type="file"
              accept={chosen.accept}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            Nothing is saved yet. You will see what would change first.
          </p>
          <div>
            <Button
              type="submit"
              disabled={!file || read.isPending || (sendsToAi && !aiOk)}
            >
              <FileUp data-icon="inline-start" aria-hidden="true" />
              Preview changes
            </Button>
          </div>
          {read.isError && (
            <p role="alert" className="text-sm text-danger">
              {read.error.message}
            </p>
          )}
        </form>
      )}

      {preview && (
        <section aria-label="Import preview" className="grid gap-3">
          <div className="flex flex-wrap gap-2">
            <Chip tone="good">{count("add")} to add</Chip>
            <Chip tone="info">{count("update")} to replace</Chip>
            <Chip tone="warn">{count("conflict")} conflicts</Chip>
            <Chip>{count("unchanged")} unchanged</Chip>
          </div>
          {(preview.source === "old_kit_zip" ||
            preview.source === "free_form") && (
            <p>
              Everything from an old folder arrives <b>unconfirmed</b> and
              marked <b>may be stale</b>. Nothing imported can switch on
              automation until you confirm it item by item.
            </p>
          )}
          {preview.notices.map((n) => (
            <p
              key={n}
              role="note"
              className="rounded-sm bg-warn-soft px-3 py-2 text-warn"
            >
              {n}
            </p>
          ))}
          <ul
            aria-label="Changes"
            className="divide-y divide-border rounded-md border border-border"
          >
            {preview.diff.map((d) => {
              const id = diffKey(d)
              return (
                <li key={id} className="grid gap-1 p-2.5">
                  <label className="flex flex-wrap items-center gap-2">
                    <Checkbox
                      aria-label={`Include ${d.entity} ${d.key}`}
                      disabled={d.change === "unchanged"}
                      checked={!skip.has(id) && d.change !== "unchanged"}
                      onCheckedChange={(v) =>
                        setSkip((s) => {
                          const n = new Set(s)
                          if (v) n.delete(id)
                          else n.add(id)
                          return n
                        })
                      }
                    />
                    <span className="font-medium">{d.key}</span>
                    <span className="text-sm text-muted-foreground">
                      {d.entity}
                    </span>
                    <Chip tone={CHANGE_TONE[d.change]}>
                      {CHANGE_LABEL[d.change]}
                    </Chip>
                  </label>
                  {(d.change === "update" || d.change === "conflict") && (
                    <dl className="grid gap-x-4 pl-7 text-sm md:grid-cols-2">
                      <div>
                        <dt className="text-muted-foreground">You have</dt>
                        <dd>{show(d.before)}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">The file has</dt>
                        <dd>{show(d.after)}</dd>
                      </div>
                    </dl>
                  )}
                </li>
              )
            })}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => write.mutate()}
              disabled={write.isPending || included === 0}
            >
              Import {included} item{included === 1 ? "" : "s"}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setPreview(null)
              }}
            >
              Cancel, change nothing
            </Button>
          </div>
          {write.isError && (
            <p role="alert" className="text-sm text-danger">
              {write.error.message}
            </p>
          )}
        </section>
      )}

      {result && (
        <p
          role="status"
          className="rounded-sm bg-good-soft px-3 py-2 text-good"
        >
          Imported. {result.created} added, {result.updated} replaced,{" "}
          {result.needs_review} waiting for your review.
        </p>
      )}
      {result && result.themes_need_review.length > 0 && (
        <div
          role="alert"
          className="grid gap-1 rounded-sm bg-warn-soft px-3 py-2 text-[0.88rem]"
        >
          <b className="font-semibold text-warn">
            {result.themes_need_review.length === 1
              ? "One theme needs review"
              : `${result.themes_need_review.length} themes need review`}
          </b>
          <span>
            Body text is below WCAG AA contrast, so these were not applied. Fix
            or accept the colours in the theme studio:{" "}
            {result.themes_need_review.map((t, i) => (
              <span key={t.id}>
                {i > 0 && ", "}
                <Link
                  to="/theme-studio/$themeId"
                  params={{ themeId: t.id }}
                  className="underline"
                >
                  {t.name}
                </Link>
              </span>
            ))}
            .
          </span>
        </div>
      )}
    </div>
  )
}
