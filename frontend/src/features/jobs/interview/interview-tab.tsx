import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CircleAlert,
  Download,
  GraduationCap,
  Loader2,
  MessagesSquare,
  PauseCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { formatCost } from "@/lib/cost"
import { listQuery } from "@/features/kit/api"
import { indexFacts } from "@/features/studio/draft"
import type { FactOut } from "@/features/studio/api"
import { applicationQuery, type JobDetail } from "../api"
import { dateText } from "../format"
import {
  estimateQuery,
  exportPack,
  generatePack,
  packKeys,
  packQuery,
  type ExportFormat,
} from "./api"
import { PracticePanel } from "./practice"
import { PackSectionView } from "./section"
import {
  basisOf,
  isOpen,
  SECTION_ORDER,
  sectionsOf,
  sectionTitle,
  type Basis,
  type InterviewPack,
  type Questions,
} from "./shapes"

const EXPORTS: { format: ExportFormat; label: string }[] = [
  { format: "docx", label: "Word (DOCX)" },
  { format: "pdf", label: "PDF" },
  { format: "txt", label: "Plain text" },
]

/** Show only the crib sheet when printing (theme tokens only; no colours here). */
const PRINT_CSS = `@media print {
  body * { visibility: hidden !important; }
  #crib-print, #crib-print * { visibility: visible !important; }
  #crib-print { position: absolute; left: 0; top: 0; width: 100%; }
}`

const STATUS_WORDS: Record<string, string> = {
  queued: "Queued",
  running: "Building",
}

export function InterviewTab({ job }: { job: JobDetail }) {
  const pack = useQuery(packQuery(job.id))
  const app = useQuery(applicationQuery(job.application_id))

  if (pack.isPending)
    return (
      <p className="text-muted-foreground">Loading the interview pack...</p>
    )
  if (pack.isError)
    return (
      <p role="alert" className="text-danger">
        Couldn't load the interview pack. {pack.error.message}
      </p>
    )
  const p = pack.data
  // No pack yet, or one only offered (no generation asked for): offer to build it.
  if (!p || (p.status === "idle" && !p.generation))
    return (
      <GeneratePanel
        jobId={job.id}
        hasApplication={!!job.application_id}
        atInterview={app.data?.stage === "interview"}
        offeredAt={p?.offered_at ?? null}
      />
    )
  return <PackView jobId={job.id} pack={p} />
}

function EstimateLine({
  jobId,
  sections,
}: {
  jobId: string
  sections?: string[]
}) {
  const e = useQuery(estimateQuery(jobId, sections))
  return (
    <p
      className="text-sm text-muted-foreground"
      aria-live="polite"
      data-estimate
    >
      {e.isPending
        ? "Estimating the cost..."
        : e.data
          ? `Estimated cost: up to ${formatCost(e.data.total_micros, { currency: e.data.currency })} for ${Object.keys(e.data.sections).length} sections. Each section reserves its own spend when it is built.`
          : `The cost estimate is not available. ${e.error?.message ?? ""}`}
    </p>
  )
}

function GeneratePanel({
  jobId,
  hasApplication,
  atInterview,
  offeredAt,
}: {
  jobId: string
  hasApplication: boolean
  atInterview: boolean
  offeredAt: string | null
}) {
  const qc = useQueryClient()
  const gen = useMutation({
    mutationFn: () => generatePack(jobId),
    onSuccess: (p) => qc.setQueryData(packKeys.pack(jobId), p),
  })
  return (
    <div className="grid gap-3">
      {(atInterview || offeredAt) && (
        <div
          role="status"
          data-offer
          className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-highlight-soft p-3 text-highlight-ink"
        >
          <GraduationCap className="size-4" aria-hidden="true" />
          <span className="font-semibold">
            {offeredAt
              ? `A pack was offered ${dateText(offeredAt)}, because this role reached the interview stage. Want it now?`
              : "This role is at the interview stage. Want a pack to prepare from?"}
          </span>
        </div>
      )}
      <div className="rounded-lg border border-dashed border-border-strong">
        <EmptyState
          icon={MessagesSquare}
          title="Interview pack"
          description={
            hasApplication
              ? "Built from the posting, the exact packet you submitted, the answers you gave and your approved facts. Every claim about you carries the Kit facts behind it."
              : "There is no application for this role yet, so the pack rests on the posting and your approved facts only."
          }
          actions={
            <Button
              size="sm"
              disabled={gen.isPending}
              onClick={() => gen.mutate()}
            >
              Generate the pack
            </Button>
          }
        />
        <div className="mx-auto mb-5 max-w-[56ch] text-center">
          <EstimateLine jobId={jobId} />
        </div>
        {gen.isError && (
          <p role="alert" className="mb-4 text-center text-sm text-danger">
            {gen.error.message}
          </p>
        )}
      </div>
    </div>
  )
}

function BasisLine({ basis }: { basis: Basis | null }) {
  if (!basis) return null
  const text =
    basis.source === "submitted_packet"
      ? [
          "Built from the packet you submitted",
          basis.packet_hash ? ` (${basis.packet_hash.slice(0, 8)})` : "",
          basis.spec_version != null
            ? `, draft version ${basis.spec_version}`
            : "",
          ".",
        ].join("")
      : basis.source === "latest_checked_spec"
        ? `Built from your latest checked draft${basis.spec_version != null ? `, version ${basis.spec_version}` : ""}: nothing has been submitted yet.`
        : "Built from the posting and your approved facts only: there is no submitted packet or checked draft."
  return (
    <div className="grid gap-1" data-basis={basis.source}>
      <p className="text-sm text-muted-foreground">{text}</p>
      {basis.posting_changed && (
        <p role="alert" className="text-sm font-semibold text-warn">
          The posting changed since you applied. What you sent was built on the
          earlier version.
        </p>
      )}
    </div>
  )
}

function ExportButtons({ jobId }: { jobId: string }) {
  const [flagged, setFlagged] = useState<string[] | null>(null)
  const run = useMutation({
    mutationFn: (fmt: ExportFormat) => exportPack(jobId, fmt),
    onSuccess: ({ blob, flagged: f, filename }) => {
      setFlagged(f)
      if (typeof URL.createObjectURL === "function") {
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      }
    },
  })
  return (
    <span className="ml-auto grid justify-items-end gap-1">
      <span className="flex flex-wrap items-center gap-1.5">
        <Download className="size-4 text-faint" aria-hidden="true" />
        {EXPORTS.map((x) => (
          <Button
            key={x.format}
            size="xs"
            variant="outline"
            disabled={run.isPending}
            onClick={() => run.mutate(x.format)}
          >
            {x.label}
          </Button>
        ))}
      </span>
      {run.isError && (
        <span role="alert" className="text-xs text-danger">
          {run.error.message}
        </span>
      )}
      {flagged && flagged.length > 0 && (
        <span role="status" className="text-xs text-warn" data-export-flagged>
          Exported. Marked as failing the truth checks:{" "}
          {flagged.map(sectionTitle).join(", ")}.
        </span>
      )}
    </span>
  )
}

function PackView({ jobId, pack }: { jobId: string; pack: InterviewPack }) {
  const qc = useQueryClient()
  const facts = useQuery(listQuery<FactOut>("facts"))
  const index = indexFacts(facts.data ?? [])
  const [practising, setPractising] = useState(false)
  const open = isOpen(pack.status)
  const pending = pack.pending_sections ?? []
  const all = sectionsOf(pack)
  const keys = [
    ...SECTION_ORDER.filter((k) => k in all),
    ...Object.keys(all).filter((k) => !SECTION_ORDER.includes(k as never)),
  ]
  const questions =
    (all.questions?.content as unknown as Questions | undefined)?.items ?? []
  const currency = useQuery({ ...estimateQuery(jobId), enabled: practising })
    .data?.currency

  const again = useMutation({
    mutationFn: () => generatePack(jobId, pending.length ? pending : undefined),
    onSuccess: (p) => qc.setQueryData(packKeys.pack(jobId), p),
  })

  return (
    <div className="grid gap-6">
      <style>{PRINT_CSS}</style>
      <header className="grid gap-2">
        <BasisLine basis={basisOf(pack)} />
        <div className="flex flex-wrap items-start gap-1.5">
          <Button
            size="sm"
            variant={practising ? "default" : "outline"}
            aria-pressed={practising}
            onClick={() => setPractising((p) => !p)}
          >
            Practice mode
          </Button>
          {pack.cost_micros > 0 && (
            <span className="self-center text-xs text-faint">
              Spent so far{" "}
              {formatCost(pack.cost_micros, { currency, compact: true })}
            </span>
          )}
          <ExportButtons jobId={jobId} />
        </div>
      </header>

      {open && (
        <div
          role="status"
          className="grid gap-1.5"
          data-pack-status={pack.status}
        >
          <span className="inline-flex items-center gap-2 text-sm font-semibold">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            {STATUS_WORDS[pack.status ?? "queued"]}: {pending.length} section
            {pending.length === 1 ? "" : "s"} to go
            {pending.length ? ` (${pending.map(sectionTitle).join(", ")})` : ""}
          </span>
          {pack.estimate_micros != null && (
            <span className="text-xs text-muted-foreground">
              Estimated up to {formatCost(pack.estimate_micros, { currency })}
            </span>
          )}
        </div>
      )}
      {pack.status === "paused" && (
        <div
          role="alert"
          className="grid gap-2 rounded-md border border-warn bg-warn-soft p-3"
        >
          <span className="inline-flex items-center gap-2 font-semibold text-warn">
            <PauseCircle className="size-4" aria-hidden="true" />
            Paused: the AI budget is used up
          </span>
          <p className="text-sm">
            {pending.length} section{pending.length === 1 ? " is" : "s are"}{" "}
            still to build ({pending.map(sectionTitle).join(", ")}), after
            spending {formatCost(pack.cost_micros, { currency })}. Nothing more
            is spent until there is budget again; it resumes on its own then.
          </p>
          <span className="flex flex-wrap gap-1.5">
            <Button asChild size="sm" variant="outline">
              <Link to="/settings/ai">Open Settings, AI</Link>
            </Button>
            <Button
              size="sm"
              disabled={again.isPending}
              onClick={() => again.mutate()}
            >
              Resume
            </Button>
          </span>
        </div>
      )}
      {pack.status === "failed" && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 text-sm text-danger"
        >
          <CircleAlert className="size-4" aria-hidden="true" />
          The pack could not be finished{pack.error ? `: ${pack.error}` : "."}
          <Button
            size="xs"
            variant="outline"
            disabled={again.isPending}
            onClick={() => again.mutate()}
          >
            Try again
          </Button>
        </div>
      )}
      {again.isError && (
        <p role="alert" className="text-sm text-danger">
          {again.error.message}
        </p>
      )}

      {practising && (
        <PracticePanel
          jobId={jobId}
          questions={questions}
          index={index}
          currency={currency}
        />
      )}

      {facts.isPending && keys.length > 0 && (
        <p className="text-muted-foreground">
          Checking claims against your Kit...
        </p>
      )}
      {facts.isError && (
        <p role="alert" className="text-danger">
          Couldn't load your Kit facts, so claims can't be checked.{" "}
          {facts.error.message}
        </p>
      )}
      {facts.isSuccess &&
        keys.map((k) => (
          <PackSectionView
            key={`${k}-${all[k].version}`}
            jobId={jobId}
            sectionKey={k}
            section={all[k]}
            note={pack.notes?.[k] ?? ""}
            index={index}
            locked={open}
          />
        ))}
      {keys.length === 0 && !open && <Chip tone="line">No sections yet</Chip>}
    </div>
  )
}
