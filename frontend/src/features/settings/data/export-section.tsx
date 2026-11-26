import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Download, ShieldAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Checkbox } from "@/components/ui/checkbox"
import { isApiError } from "@/lib/api/client"
import {
  downloadExport,
  exportKit,
  exportPreview,
  type ExportKind,
  type ExportPreview,
  type ExportResult,
  type PersonalDetailHit,
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
  const [ack, setAck] = useState(false)
  const check = useMutation({
    mutationFn: () => exportPreview(kind),
    onSuccess: (p) => {
      setPreview(p)
      setAck(false)
    },
  })
  const make = useMutation({
    mutationFn: () => exportKit(kind, ack),
    onSuccess: setFile,
    // The server found personal details the owner has not acknowledged: show them.
    onError: (e) => {
      if (isApiError(e, 409)) check.mutate()
    },
  })
  const fetchFile = useMutation({
    mutationFn: () => downloadExport(file as ExportResult),
    onError: (e) => {
      if (isApiError(e, 404)) setFile(null)
    },
  })
  const hits = preview?.personal_details_found ?? []
  const shared = kind === "share_setup"
  const blocked = make.isError && isApiError(make.error, 409)
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
        <PersonalDetails hits={hits} ack={ack} onAck={setAck} />
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
          onClick={() => {
            setFile(null)
            make.mutate()
          }}
        >
          <Download data-icon="inline-start" aria-hidden="true" />
          Create file
        </Button>
        {file && (
          <Button
            variant="link"
            disabled={fetchFile.isPending}
            onClick={() => fetchFile.mutate()}
          >
            Download {file.file_name}
          </Button>
        )}
      </div>
      {file && (
        <p className="text-sm text-muted-foreground">
          The link works until{" "}
          {new Date(file.expires_at).toLocaleTimeString(undefined, {
            timeStyle: "short",
          })}
          .
        </p>
      )}
      {make.isError && (
        <p role="alert" className="text-sm text-danger">
          {blocked
            ? "Personal details were found. Read them below, then remove them or tick the box to include them anyway."
            : make.error.message}
        </p>
      )}
      {fetchFile.isError && (
        <p role="alert" className="text-sm text-danger">
          {fetchFile.error.message}
        </p>
      )}
    </article>
  )
}

/** What the scan found, and the owner's explicit choice to share it anyway. */
function PersonalDetails({
  hits,
  ack,
  onAck,
}: {
  hits: PersonalDetailHit[]
  ack: boolean
  onAck: (v: boolean) => void
}) {
  return (
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
        <p>
          Remove these before you share the file, or include them knowingly.
        </p>
        <label className="mt-2 flex items-center gap-2 font-medium">
          <Checkbox checked={ack} onCheckedChange={(v) => onAck(v === true)} />I
          have read these and want to include them
        </label>
      </AlertDescription>
    </Alert>
  )
}
