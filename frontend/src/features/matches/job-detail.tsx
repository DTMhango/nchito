import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  AlertTriangle,
  Check,
  CircleCheck,
  CircleHelp,
  CircleX,
  Clock,
  ExternalLink,
  MoreHorizontal,
  Pin,
  PinOff,
  Scale,
  Send,
  Sparkles,
  X,
} from "lucide-react"
import { Chip, type ChipTone } from "@/components/chip"
import { JobEmployerChip } from "@/features/employers/employer-chip"
import { EmptyState } from "@/components/empty-state"
import { EvidencePopover } from "@/components/evidence-popover"
import { KeyHint } from "@/components/key-hint"
import { ScoreRing } from "@/components/score-ring"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import {
  assessmentsQuery,
  customFacetsQuery,
  factsQuery,
  jobQuery,
  rubricQuery,
} from "./api"
import { valueLabel } from "./filters"
import {
  age,
  deadlineLabel,
  payBand,
  placeLabel,
  workModelLabel,
} from "./format"
import { FeedbackControl } from "./feedback/feedback-control"
import { TagEditor } from "./tag-editor"
import type { AssessmentOut, FactOut, JobDetail } from "./types"
import { WhySection } from "./why-section"

export const SNOOZE_CHOICES = [
  { days: 1, label: "Until tomorrow" },
  { days: 3, label: "For 3 days" },
  { days: 7, label: "For a week" },
  { days: 14, label: "For 2 weeks" },
] as const

export type DetailActions = {
  tailor: () => void
  apply: () => void
  skip: () => void
  snooze: (days: number) => void
  pin: () => void
  shortlist: () => void
  archive: () => void
  appliedMyself: () => void
  release: () => void
  recheck: () => void
}

type JobDetailPaneProps = {
  id: string
  actions: DetailActions
  snoozeOpen: boolean
  onSnoozeOpenChange: (open: boolean) => void
}

/** The detail pane: everything needed to decide about one role, without leaving the list. */
export function JobDetailPane({
  id,
  actions,
  snoozeOpen,
  onSnoozeOpenChange,
}: JobDetailPaneProps) {
  const job = useQuery(jobQuery(id))
  const assessments = useQuery(assessmentsQuery(id))

  if (job.isLoading) return <DetailSkeleton />
  if (job.isError || !job.data)
    return (
      <EmptyState
        icon={AlertTriangle}
        title="This role could not be loaded"
        description={
          job.error instanceof Error
            ? job.error.message
            : "Try again in a moment."
        }
      />
    )
  const j = job.data
  const items = assessments.data?.items ?? []
  const a =
    items.find((x) => x.is_conflict_winner) ??
    [...items].sort((x, y) => (y.score ?? 0) - (x.score ?? 0))[0]
  const source = j.source

  return (
    <article
      className="max-w-[980px] pr-3"
      aria-label={`${j.title}, ${j.employer}`}
    >
      <header className="grid gap-2">
        <span className="eyebrow">
          {j.employer}
          {source ? ` · ${source}` : ""}
          {j.posted_at
            ? ` · posted ${age(j.posted_at) === "today" ? "today" : `${age(j.posted_at)} ago`}`
            : ""}
        </span>
        <h2 className="text-xl">{j.title}</h2>
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-[0.9rem] text-muted-foreground">
          <Chip tone="line">{placeLabel(j.location)}</Chip>
          {workModelLabel(j.facets.work_model?.value) && (
            <Chip tone="line">
              {workModelLabel(j.facets.work_model?.value)}
            </Chip>
          )}
          <PayChip job={j} />
          <Chip tone="line" icon={Clock}>
            {deadlineLabel(j.deadline)}
          </Chip>
          {j.conflict_state === "held" && (
            <Chip tone="warn" icon={Scale}>
              Held · {j.conflict_note ?? "outranked at this employer"}
            </Chip>
          )}
          {j.conflict_state === "winner" && (
            <Chip tone="good" icon={Scale}>
              Best role at this employer
            </Chip>
          )}
          {j.availability === "closed" && <Chip tone="danger">Closed</Chip>}
          <JobEmployerChip jobId={j.id} />
        </div>
        <TagEditor job={j} />
      </header>

      <div
        className="my-4 flex flex-wrap gap-1.5 border-b border-border pb-4.5"
        role="toolbar"
        aria-label="Actions"
      >
        <Button onClick={actions.tailor}>
          <Sparkles data-icon="inline-start" aria-hidden="true" />
          Tailor
          <KeyHint keys="T" tone="inverse" />
        </Button>
        <Button variant="outline" onClick={actions.apply}>
          <Send data-icon="inline-start" aria-hidden="true" />
          Apply
          <KeyHint keys="A" />
        </Button>
        <Button variant="outline" onClick={actions.skip}>
          <X data-icon="inline-start" aria-hidden="true" />
          Skip
          <KeyHint keys="S" />
        </Button>
        <DropdownMenu open={snoozeOpen} onOpenChange={onSnoozeOpenChange}>
          <DropdownMenuTrigger asChild>
            <Button variant="outline">
              <Clock data-icon="inline-start" aria-hidden="true" />
              Snooze
              <KeyHint keys="Z" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            onKeyDown={(e) => {
              const n = Number(e.key)
              const choice = SNOOZE_CHOICES[n - 1]
              if (choice) {
                e.preventDefault()
                onSnoozeOpenChange(false)
                actions.snooze(choice.days)
              }
            }}
          >
            <DropdownMenuLabel>Hide it from the list</DropdownMenuLabel>
            {SNOOZE_CHOICES.map((c, i) => (
              <DropdownMenuItem
                key={c.days}
                onSelect={() => actions.snooze(c.days)}
              >
                {c.label}
                <KeyHint keys={String(i + 1)} className="ml-auto" />
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="ghost" onClick={actions.pin}>
          {j.pinned ? (
            <PinOff data-icon="inline-start" aria-hidden="true" />
          ) : (
            <Pin data-icon="inline-start" aria-hidden="true" />
          )}
          {j.pinned ? "Unpin" : "Pin"}
          <KeyHint keys="P" />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="More actions">
              <MoreHorizontal aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {j.triage !== "shortlisted" && (
              <DropdownMenuItem onSelect={actions.shortlist}>
                Shortlist
              </DropdownMenuItem>
            )}
            {j.triage !== "archived" && (
              <DropdownMenuItem onSelect={actions.archive}>
                Archive
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Corrections</DropdownMenuLabel>
            <DropdownMenuItem onSelect={actions.appliedMyself}>
              I applied myself…
            </DropdownMenuItem>
            {j.conflict_state === "held" && (
              <DropdownMenuItem onSelect={actions.release}>
                Release this held role…
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={actions.recheck}>
              Recheck the posting
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="link" asChild className="ml-auto">
          <Link to="/jobs/$id" params={{ id: j.id }}>
            Full job page
            <ExternalLink data-icon="inline-end" aria-hidden="true" />
          </Link>
        </Button>
      </div>

      <div className="grid gap-7 2xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="grid content-start gap-6">
          <ScoreBreakdown assessment={a} loading={assessments.isLoading} />
          <FilterResults assessment={a} />
        </div>
        <div className="grid content-start gap-6">
          <FitAndGaps assessment={a} />
        </div>
      </div>

      <WhySection jobId={j.id} className="mt-7" />

      <FeedbackControl
        jobId={j.id}
        campaignId={a?.campaign_id ?? null}
        className="mt-7"
      />

      <Block title="Requirements" className="mt-7">
        {j.requirements.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No requirements were read from this posting.
          </p>
        ) : (
          <div className="overflow-x-auto border-t border-border">
            <table className="w-full border-collapse text-[0.88rem]">
              <thead>
                <tr>
                  {["Requirement", "Kind", "Skill"].map((h) => (
                    <th
                      key={h}
                      className="border-b border-border py-2 pr-2.5 text-left eyebrow whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {j.requirements.map((r, i) => (
                  <tr key={`${r.text}-${i}`}>
                    <td className="border-b border-border py-1.5 pr-2.5 align-top">
                      {r.text}
                    </td>
                    <td className="border-b border-border py-1.5 pr-2.5 align-top">
                      <Chip
                        tone={r.kind === "preferred" ? "neutral" : "primary"}
                      >
                        {r.kind === "preferred" ? "Preferred" : "Required"}
                      </Chip>
                    </td>
                    <td className="border-b border-border py-1.5 pr-2.5 align-top text-muted-foreground">
                      {r.skill ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      <Block title="Facets from the posting" className="mt-7">
        <FacetList job={j} />
      </Block>

      <Block title="Posting text" className="mt-7">
        {j.raw_text ? (
          <details className="group/posting">
            <summary className="cursor-pointer text-sm font-medium text-primary-ink">
              <span className="group-open/posting:hidden">
                Show the posting
              </span>
              <span className="hidden group-open/posting:inline">
                Hide the posting
              </span>
            </summary>
            <div className="mt-2 max-w-[72ch] text-[0.92rem] leading-relaxed whitespace-pre-line text-muted-foreground">
              {j.raw_text}
            </div>
          </details>
        ) : (
          <p className="text-sm text-muted-foreground">
            The posting text was not captured. Open the full job page to read it
            at the source.
          </p>
        )}
      </Block>
    </article>
  )
}

function Block({
  title,
  children,
  className,
}: {
  title: string
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn("grid min-w-0 content-start gap-2.5", className)}>
      <h3 className="eyebrow">{title}</h3>
      {children}
    </section>
  )
}

function PayChip({ job }: { job: JobDetail }) {
  const band = payBand(job.pay)
  if (job.pay.state === "stated" && band)
    return (
      <Chip tone="line" className="num">
        {band}
      </Chip>
    )
  if (job.pay.state === "estimated" && band)
    return (
      <EvidencePopover
        title="Estimated pay, not from the posting"
        content={job.pay.estimate_assumptions ?? "No assumptions recorded."}
        source={[job.pay.estimate_source, job.pay.estimated_on]
          .filter(Boolean)
          .join(" · ")}
        triggerLabel={`Estimated pay ${band}`}
      >
        <Chip tone="line" className="num italic">
          ~{band} est.
        </Chip>
      </EvidencePopover>
    )
  return <Chip tone="neutral">Pay not stated</Chip>
}

// ---- score ------------------------------------------------------------------------------------

function ScoreBreakdown({
  assessment,
  loading,
}: {
  assessment: AssessmentOut | undefined
  loading: boolean
}) {
  const rubric = useQuery({
    ...rubricQuery(assessment?.rubric_id ?? ""),
    enabled: !!assessment?.rubric_id,
  })
  const facts = useQuery(factsQuery())
  if (loading) return <Skeleton className="h-40" />
  if (!assessment)
    return (
      <Block title="Score breakdown">
        <p className="text-sm text-muted-foreground">
          Not scored yet. It is scored when a campaign that covers it next runs.
        </p>
      </Block>
    )
  const criteria = rubric.data?.body.criteria ?? []
  const weightOf = (name: string) =>
    criteria.find((c) => c.name === name)?.weight
  const maxWeight = Math.max(25, ...criteria.map((c) => c.weight))
  const factById = new Map((facts.data?.items ?? []).map((f) => [f.id, f]))
  const score = assessment.override?.score ?? assessment.score ?? 0
  return (
    <Block title="Score breakdown · weight · points">
      <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-5.5">
        <ScoreRing score={score} size={88} />
        <div role="table" aria-label="Score per criterion">
          {assessment.ratings.map((r) => {
            const w = weightOf(r.criterion)
            const pts = w != null ? Math.round((w * r.rating) / 5) : null
            return (
              <div
                key={r.criterion}
                role="row"
                className="grid grid-cols-[minmax(0,150px)_34px_minmax(0,1fr)_40px] items-center gap-2.5 py-1 text-[0.88rem]"
              >
                <span role="cell" className="min-w-0">
                  <CriterionEvidence
                    name={r.criterion}
                    note={r.note}
                    facts={
                      r.evidence_fact_ids?.map(
                        (id) => factById.get(id) ?? id
                      ) ?? []
                    }
                  />
                </span>
                <span
                  role="cell"
                  className="text-right num text-[0.78rem] text-faint"
                >
                  {w ?? "–"}
                </span>
                <span
                  role="cell"
                  aria-label={`Rated ${r.rating} of 5`}
                  className="h-2 overflow-hidden rounded-full bg-sunken"
                  style={{ width: `${((w ?? maxWeight) / maxWeight) * 100}%` }}
                >
                  <i
                    className="block h-full rounded-[inherit] bg-primary"
                    style={{ width: `${(r.rating / 5) * 100}%` }}
                  />
                </span>
                <span role="cell" className="text-right num font-semibold">
                  {pts ?? `${r.rating}/5`}
                </span>
              </div>
            )
          })}
          <div
            role="row"
            className="mt-1 grid grid-cols-[minmax(0,150px)_34px_minmax(0,1fr)_40px] items-center gap-2.5 border-t border-border pt-2 text-[0.88rem] font-semibold"
          >
            <span role="cell">Total</span>
            <span
              role="cell"
              className="text-right num text-[0.78rem] text-faint"
            >
              100
            </span>
            <span role="cell" />
            <span role="cell" className="text-right num">
              {score}
            </span>
          </div>
          {assessment.override && (
            <p className="mt-2 text-xs text-muted-foreground">
              Overridden by {assessment.override.by}:{" "}
              {assessment.override.reason}
            </p>
          )}
        </div>
      </div>
    </Block>
  )
}

function CriterionEvidence({
  name,
  note,
  facts,
}: {
  name: string
  note?: string | null
  facts: (FactOut | string)[]
}) {
  const content =
    facts.length === 0 ? (
      <span>No evidence cited, so the rating is capped at 3.</span>
    ) : (
      <ul className="grid gap-1">
        {facts.map((f) =>
          typeof f === "string" ? (
            <li key={f}>Fact {f.slice(0, 8)}</li>
          ) : (
            <li key={f.id}>
              <b className="num">{f.code}</b> {f.text}
            </li>
          )
        )}
      </ul>
    )
  return (
    <EvidencePopover
      title={`${name}: evidence`}
      content={content}
      source={note ?? undefined}
      triggerClassName="max-w-full truncate text-left underline decoration-border-strong decoration-dotted underline-offset-4"
      triggerLabel={`${name}, show evidence`}
    >
      {name}
    </EvidencePopover>
  )
}

const FILTER_TONE: Record<
  string,
  { tone: ChipTone; icon: typeof Check; text: string }
> = {
  pass: { tone: "good", icon: CircleCheck, text: "pass" },
  fail: { tone: "danger", icon: CircleX, text: "fail" },
  unknown: { tone: "neutral", icon: CircleHelp, text: "unknown" },
}

function FilterResults({
  assessment,
}: {
  assessment: AssessmentOut | undefined
}) {
  if (!assessment) return null
  return (
    <Block title="Hard filters">
      <ul className="flex flex-wrap gap-1.5">
        {assessment.filter_results.map((f) => {
          const t = FILTER_TONE[f.result]
          return (
            <li key={f.name}>
              <Chip
                tone={f.result === "unknown" ? "line" : t.tone}
                icon={t.icon}
                className="whitespace-normal"
              >
                {f.name}: {t.text}
                <span className="font-normal opacity-80">· {f.reason}</span>
              </Chip>
            </li>
          )
        })}
      </ul>
    </Block>
  )
}

function FitAndGaps({ assessment }: { assessment: AssessmentOut | undefined }) {
  const facts = useQuery(factsQuery())
  if (!assessment) return null
  const factById = new Map((facts.data?.items ?? []).map((f) => [f.id, f]))
  const fits = assessment.ratings
    .filter((r) => r.rating >= 4)
    .map((r) => {
      const f = r.evidence_fact_ids?.map((id) => factById.get(id)).find(Boolean)
      return {
        key: r.criterion,
        text: f ? `${r.criterion}: ${f.text}` : (r.note ?? r.criterion),
      }
    })
  return (
    <>
      <Block title="Why it fits">
        {fits.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No criterion rated strongly with evidence.
          </p>
        ) : (
          <ul className="grid gap-2">
            {fits.map((f) => (
              <li
                key={f.key}
                className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 leading-[1.45]"
              >
                <Check className="mt-0.5 size-4 text-good" aria-hidden="true" />
                <span>{f.text}</span>
              </li>
            ))}
          </ul>
        )}
      </Block>
      <Block title="Gaps">
        {assessment.gaps.length === 0 ? (
          <p className="text-sm text-muted-foreground">No gaps found.</p>
        ) : (
          <ul className="grid gap-2">
            {assessment.gaps.map((g) => (
              <li
                key={g}
                className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 leading-[1.45]"
              >
                <AlertTriangle
                  className="mt-0.5 size-4 text-warn"
                  aria-hidden="true"
                />
                <span>{g}</span>
              </li>
            ))}
          </ul>
        )}
      </Block>
    </>
  )
}

// ---- facets -----------------------------------------------------------------------------------

const FACET_LABELS: [keyof JobDetail["facets"], string][] = [
  ["relocation_required", "Relocation required"],
  ["visa_sponsorship", "Sponsorship offered"],
  ["relocation_assistance", "Relocation assistance"],
  ["work_model", "Work model"],
  ["remote_scope", "Remote scope"],
  ["where_must_live", "Where you must live"],
  ["work_rights", "Work rights"],
  ["timezone_overlap", "Time-zone overlap"],
  ["hiring_arrangement", "Hiring arrangement"],
  ["employment_type", "Employment type"],
  ["min_education", "Minimum education"],
  ["years_experience", "Years of experience"],
  ["travel_percent", "Travel"],
  ["needs_account", "Needs an account to apply"],
]

function display(key: string, value: unknown): string {
  if (value == null) return "Not stated"
  if (typeof value === "string") return valueLabel(value)
  if (typeof value === "number")
    return key === "travel_percent" ? `${value}%` : String(value)
  const v = value as Record<string, unknown>
  if (key === "min_education")
    return `${valueLabel(String(v.level))}${v.level !== "none_stated" ? (v.required ? ", required" : ", preferred") : ""}`
  if (key === "where_must_live")
    return v.kind === "places"
      ? ((v.places as string[]) ?? []).join(", ")
      : valueLabel(String(v.kind))
  if (key === "timezone_overlap")
    return v.hours ? `${v.hours} h with ${v.zone ?? "the team"}` : "Not stated"
  return JSON.stringify(value)
}

function FacetList({ job }: { job: JobDetail }) {
  const questions = useQuery(customFacetsQuery()).data?.items ?? []
  const questionFor = (key: string) =>
    questions.find((q) => q.key === key)?.question ?? valueLabel(key)
  const rows = FACET_LABELS.map(([key, label]) => {
    const raw = job.facets[key] as
      { value: unknown; evidence?: string | null } | null | undefined
    return {
      key,
      label,
      value: display(key, raw?.value),
      evidence: raw?.evidence,
    }
  })
  const lists: [string, string[] | undefined][] = [
    ["Required skills", job.facets.required_skills],
    ["Preferred skills", job.facets.preferred_skills],
    ["Required qualifications", job.facets.required_qualifications],
    ["Languages", job.facets.languages],
  ]
  return (
    <dl className="grid gap-x-6 sm:grid-cols-2">
      {rows.map((r) => (
        <div
          key={r.key}
          className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 text-sm"
        >
          <dt className="text-muted-foreground">{r.label}</dt>
          <dd className="text-right">
            {r.evidence ? (
              <EvidencePopover
                title="From the posting"
                content={`“${r.evidence}”`}
                triggerLabel={`${r.label}: ${r.value}. Show the sentence from the posting`}
                triggerClassName="underline decoration-border-strong decoration-dotted underline-offset-4"
              >
                {r.value}
              </EvidencePopover>
            ) : (
              <span className={cn(r.value === "Not stated" && "text-faint")}>
                {r.value}
              </span>
            )}
          </dd>
        </div>
      ))}
      {lists.map(([label, list]) => (
        <div
          key={label}
          className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 text-sm"
        >
          <dt className="text-muted-foreground">{label}</dt>
          <dd className={cn("text-right", !list?.length && "text-faint")}>
            {list?.length ? list.join(", ") : "Not stated"}
          </dd>
        </div>
      ))}
      {Object.entries(job.custom_facets).map(([key, v]) => (
        <div
          key={key}
          className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 text-sm"
        >
          <dt className="text-muted-foreground">{questionFor(key)}</dt>
          <dd className="text-right">
            {v.evidence ? (
              <EvidencePopover
                title={`Answered by ${v.model ?? "a model"}`}
                content={`“${v.evidence}”`}
                triggerClassName="underline decoration-border-strong decoration-dotted underline-offset-4"
              >
                {valueLabel(v.value)}
              </EvidencePopover>
            ) : (
              <span className={cn(v.value === "not_stated" && "text-faint")}>
                {valueLabel(v.value)}
              </span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function DetailSkeleton() {
  return (
    <div
      className="grid max-w-[720px] gap-3 pr-3"
      aria-busy="true"
      aria-label="Loading the role"
    >
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-8 w-3/4" />
      <Skeleton className="h-6 w-1/2" />
      <Skeleton className="mt-4 h-9 w-full" />
      <Skeleton className="mt-4 h-40 w-full" />
    </div>
  )
}
