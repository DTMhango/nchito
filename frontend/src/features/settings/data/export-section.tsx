import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Download, ShieldAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  exportKit,
  exportPreview,
  type ExportKind,
  type ExportPreview,
  type ExportResult,
} from "./api"

const KINDS: { kind: ExportKind; title: string; plain: string; who: string }[] =
  [
    {
      kind: "personal_backup",
      title: "Personal backup",
      plain:
        "Everything: your facts, experience, answers, documents, application history and rules. It is about you.",
      who: "Keep it private. Use it to move to a new server or to restore.",
    },
    {
      kind: "share_setup",
      title: "Shareable template",
      plain:
        "Only the how: scoring rubrics, templates, themes, rule types and sources. No facts, no documents, no history.",
      who: "Safe to give to a friend, after you have read the personal-details check.",
    },
  ]

export function ExportSection() {
  return (
    <section aria-labelledby="export-h" className="grid gap-4 panel p-4">
      <div>
        <h3 id="export-h" className="text-md">
          Export
        </h3>
        <p className="text-muted-foreground">
          Two different files. Choose by who will receive it.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {KINDS.map((k) => (
          <ExportCard key={k.kind} {...k} />
        ))}
      </div>
    </section>
  )
}

function ExportCard({ kind, title, plain, who }: (typeof KINDS)[number]) {
  const [preview, setPreview] = useState<ExportPreview | null>(null)
  const [file, setFile] = useState<ExportResult | null>(null)
  const check = useMutation({
    mutationFn: () => exportPreview(kind),
    onSuccess: setPreview,
  })
  const make = useMutation({
    mutationFn: () => exportKit(kind),
    onSuccess: setFile,
  })
  const hits = preview?.personal_details_found ?? []
  const shared = kind === "share_setup"
  return (
    <article
      aria-label={title}
      className="grid content-start gap-3 rounded-md border border-border bg-surface p-3"
    >
      <h4 className="font-semibold">{title}</h4>
      <p>{plain}</p>
      <p className="text-sm text-muted-foreground">{who}</p>
      {preview && (
        <ul
          aria-label={`What ${title} contains`}
          className="num text-sm text-muted-foreground"
        >
          {Object.entries(preview.counts).map(([k, n]) => (
            <li key={k}>
              {n} {k.replaceAll("_", " ")}
            </li>
          ))}
        </ul>
      )}
      {preview && shared && hits.length > 0 && (
        <Alert variant="destructive">
          <ShieldAlert aria-hidden="true" />
          <AlertTitle>
            {hits.length} personal detail{hits.length === 1 ? "" : "s"} found
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-1 grid gap-1">
              {hits.map((h) => (
                <li key={h.path + h.excerpt}>
                  <span className="font-medium">{h.kind}</span> in {h.path}:{" "}
                  {h.excerpt}
                </li>
              ))}
            </ul>
            Remove these before you share the file.
          </AlertDescription>
        </Alert>
      )}
      {preview && shared && hits.length === 0 && (
        <p className="text-sm text-good">No personal details found.</p>
      )}
      {check.isError && (
        <p role="alert" className="text-sm text-danger">
          {check.error.message}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" onClick={() => check.mutate()}>
          {preview ? "Check again" : "See what is inside"}
        </Button>
        <Button
          disabled={!preview || make.isPending}
          onClick={() => make.mutate()}
        >
          <Download data-icon="inline-start" aria-hidden="true" />
          Create file
        </Button>
        {file && (
          <a
            className="font-medium text-primary-ink underline"
            href={file.download_url}
            download={file.file_name}
          >
            Download {file.file_name}
          </a>
        )}
      </div>
      {make.isError && (
        <p role="alert" className="text-sm text-danger">
          {make.error.message}
        </p>
      )}
    </article>
  )
}
