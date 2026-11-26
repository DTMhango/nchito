import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CircleAlert,
  Download,
  GraduationCap,
  MessagesSquare,
  PauseCircle,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { formatCost } from "@/lib/cost"
import { listQuery } from "@/features/kit/api"
import { indexFacts } from "@/features/studio/draft"
import type { FactOut } from "@/features/studio/api"
import { applicationQuery, type JobDetail } from "../api"
import { dateText } from "../format"
import type { InterviewPack, PackSectionKey } from "../w3-pending-types"
import {
  estimateQuery,
  exportUrl,
  generatePack,
  packKeys,
  packQuery,
  regenerateSection,
  restoreVersion,
  resumePack,
  saveItem,
  saveNotes,
  setFavourite,
  type ExportFormat,
} from "./api"
import { PracticePanel } from "./practice"
import { PackSectionView, type SectionActions } from "./section"

const SECTION_ORDER: PackSectionKey[] = [
  "role_brief",
  "why_you",
  "questions",
  "stories",
  "ask",
  "gaps",
  "logistics",
  "crib",
]

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

export function InterviewTab({ job }: { job: JobDetail }) {
  if (!job.application_id)
    return (
      <EmptyState
        icon={MessagesSquare}
        title="No application yet"
        description="The interview pack is built from the documents you sent and the answers you gave, so it starts once there is an application for this role."
      />
    )
  return <AppInterview appId={job.application_id} />
}

function AppInterview({ appId }: { appId: string }) {
  const pack = useQuery(packQuery(appId))
  const app = useQuery(applicationQuery(appId))

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
  if (!pack.data)
    return (
      <GeneratePanel
        appId={appId}
        atInterview={app.data?.stage === "interview"}
      />
    )
  return <PackView appId={appId} pack={pack.data} />
}

function GeneratePanel({
  appId,
  atInterview,
}: {
  appId: string
  atInterview: boolean
}) {
  const qc = useQueryClient()
  const estimate = useQuery(estimateQuery(appId, true))
  const gen = useMutation({
    mutationFn: () => generatePack(appId),
    onSuccess: (p) => qc.setQueryData(packKeys.pack(appId), p),
  })
  const e = estimate.data
  return (
    <div className="grid gap-3">
      {atInterview && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-highlight-soft p-3 text-highlight-ink"
        >
          <GraduationCap className="size-4" aria-hidden="true" />
          <span className="font-semibold">
            This role is at the interview stage. Want a pack to prepare from?
          </span>
        </div>
      )}
      <div className="rounded-lg border border-dashed border-border-strong">
        <EmptyState
          icon={MessagesSquare}
          title="Interview pack"
          description="Built from the posting, the exact documents you sent, the answers you gave and your approved facts. Every claim about you carries the Kit facts behind it."
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
        <p
          className="mx-auto mb-5 max-w-[56ch] text-center text-sm text-muted-foreground"
          aria-live="polite"
        >
          {estimate.isPending
            ? "Estimating the cost..."
            : e
              ? `Estimated cost: about ${formatCost(e.cost_micros, { currency: e.currency })} for ${e.sections} sections on ${e.model}. You can stop at any time.`
              : "The cost estimate is not available."}
        </p>
        {gen.isError && (
          <p role="alert" className="mb-4 text-center text-sm text-danger">
            {gen.error.message}
          </p>
        )}
      </div>
    </div>
  )
}

function PackView({ appId, pack }: { appId: string; pack: InterviewPack }) {
  const qc = useQueryClient()
  const facts = useQuery(listQuery<FactOut>("facts"))
  const index = indexFacts(facts.data ?? [])
  const [practising, setPractising] = useState(false)
  const put = (p: InterviewPack) => qc.setQueryData(packKeys.pack(appId), p)
  const onError = (e: Error) => toast.error(e.message)

  const mutate = useMutation({
    mutationFn: (run: () => Promise<InterviewPack>) => run(),
    onSuccess: put,
    onError,
  })
  const resume = useMutation({
    mutationFn: () => resumePack(appId),
    onSuccess: put,
    onError,
  })

  const sections = SECTION_ORDER.map((k) =>
    pack.sections.find((s) => s.key === k)
  ).filter((s) => !!s)
  const questions =
    pack.sections.find((s) => s.key === "questions")?.items ?? []
  const actionsFor = (key: PackSectionKey): SectionActions => ({
    busy: mutate.isPending,
    saveItem: (id, text) => {
      const old = pack.sections
        .find((s) => s.key === key)
        ?.items.find((i) => i.id === id)
      mutate.mutate(() =>
        saveItem(appId, key, id, { text, fact_ids: old?.fact_ids ?? [] })
      )
    },
    saveNotes: (notes) => mutate.mutate(() => saveNotes(appId, key, notes)),
    regenerate: () => mutate.mutate(() => regenerateSection(appId, key)),
    restore: (v) => mutate.mutate(() => restoreVersion(appId, key, v)),
    favourite: (id, on) => mutate.mutate(() => setFavourite(appId, id, on)),
  })

  return (
    <div className="grid gap-6">
      <style>{PRINT_CSS}</style>
      <header className="grid gap-2">
        <p className="text-sm text-muted-foreground" data-based-on>
          Built from packet{" "}
          <b className="text-foreground">{pack.based_on.packet_label}</b> (CV{" "}
          <b className="text-foreground">{pack.based_on.cv_version}</b>),{" "}
          {dateText(pack.based_on.generated_at)}.
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            size="sm"
            variant={practising ? "default" : "outline"}
            aria-pressed={practising}
            onClick={() => setPractising((p) => !p)}
          >
            Practice mode
          </Button>
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            <Download className="size-4 text-faint" aria-hidden="true" />
            {EXPORTS.map((x) => (
              <Button key={x.format} asChild size="xs" variant="outline">
                <a href={exportUrl(appId, x.format)} download>
                  {x.label}
                </a>
              </Button>
            ))}
          </span>
        </div>
      </header>

      {pack.status === "generating" && (
        <div role="status" className="grid gap-1.5">
          <span className="text-sm font-semibold">
            Building the pack: {pack.progress.done} of {pack.progress.total}{" "}
            sections
          </span>
          <progress
            className="h-2 w-full accent-primary"
            max={pack.progress.total}
            value={pack.progress.done}
            aria-label="Pack progress"
          />
        </div>
      )}
      {pack.status === "paused_budget" && (
        <div
          role="alert"
          className="grid gap-2 rounded-md border border-warn bg-warn-soft p-3"
        >
          <span className="inline-flex items-center gap-2 font-semibold text-warn">
            <PauseCircle className="size-4" aria-hidden="true" />
            Paused: the AI budget is used up
          </span>
          <p className="text-sm">
            {pack.progress.done} of {pack.progress.total} sections are done
            {pack.paused
              ? `, after spending ${formatCost(pack.paused.spent_micros)} of ${formatCost(pack.paused.cap_micros)}`
              : ""}
            . Nothing more is spent until you raise the budget.
          </p>
          <span className="flex flex-wrap gap-1.5">
            <Button asChild size="sm" variant="outline">
              <Link to="/settings/ai">Open Settings, AI</Link>
            </Button>
            <Button
              size="sm"
              disabled={resume.isPending}
              onClick={() => resume.mutate()}
            >
              Resume
            </Button>
          </span>
        </div>
      )}
      {pack.status === "failed" && (
        <p
          role="alert"
          className="inline-flex items-center gap-2 text-sm text-danger"
        >
          <CircleAlert className="size-4" aria-hidden="true" />
          The pack could not be finished. Regenerate a section to try again.
        </p>
      )}

      {practising && (
        <PracticePanel
          appId={appId}
          questions={questions.filter((q) => q.question)}
          facts={facts.data ?? []}
        />
      )}

      {facts.isPending && sections.length > 0 && (
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
        sections.map((s) => (
          <PackSectionView
            key={`${s.key}-${s.version}`}
            section={s}
            index={index}
            actions={actionsFor(s.key)}
          />
        ))}
      {sections.length === 0 && pack.status !== "generating" && (
        <Chip tone="line">No sections yet</Chip>
      )}
    </div>
  )
}
