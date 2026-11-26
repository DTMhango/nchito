import { useQuery } from "@tanstack/react-query"
import { SectionHeader } from "@/components/page-header"
import { Chip } from "@/components/chip"
import { EvidencePopover } from "@/components/evidence-popover"
import { assessmentsQuery, type JobDetail } from "../api"
import { ConflictStatus } from "../conflict-status"
import {
  dateText,
  deadlineText,
  facetLines,
  locationText,
  picture,
} from "../format"
import { NotesEditor } from "../notes-editor"
import { TagsEditor } from "../tags-editor"
import { pickAssessment } from "./fit-tab"

const SKILL_LISTS: [keyof JobDetail["facets"], string][] = [
  ["required_skills", "Required skills"],
  ["preferred_skills", "Preferred skills"],
  ["required_qualifications", "Required qualifications"],
  ["languages", "Languages"],
]

export function OverviewTab({ job }: { job: JobDetail }) {
  const assessments = useQuery(assessmentsQuery(job.id))
  const a = pickAssessment(assessments.data ?? [])
  const fits = (a?.ratings ?? []).filter((r) => r.rating >= 4 && r.note)
  const lines = facetLines(job.facets)

  return (
    <div className="grid gap-7">
      <section aria-label="Picture in plain words" className="grid gap-2">
        <SectionHeader title="At a glance" />
        <dl className="grid gap-2 panel p-4">
          {picture(job).map((p) => (
            <div
              key={p.label}
              className="grid gap-0.5 sm:grid-cols-[110px_1fr] sm:gap-3"
            >
              <dt className="eyebrow">{p.label}</dt>
              <dd>{p.text}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-label="Key facts" className="grid gap-2">
        <SectionHeader
          title="Key facts"
          aside="Hover, tap or focus a value to see the sentence it came from"
        />
        <dl className="grid gap-x-6 panel p-4 sm:grid-cols-2">
          <Fact label="Employer" value={job.canonical_employer} />
          <Fact label="Location" value={locationText(job.location)} />
          <Fact label="Deadline" value={deadlineText(job.deadline)} />
          <Fact label="Posted" value={dateText(job.posted_at)} />
          <Fact
            label="Apply method"
            value={job.apply_method.replaceAll("_", " ")}
          />
          {job.function && <Fact label="Function" value={job.function} />}
          {job.level && <Fact label="Level" value={job.level} />}
          {lines.map((l) => (
            <div
              key={l.key}
              className="flex items-baseline justify-between gap-3 border-t border-border py-2 first:border-t-0"
            >
              <dt className="text-sm text-muted-foreground">{l.label}</dt>
              <dd>
                <EvidencePopover
                  title={l.label}
                  triggerLabel={`${l.label}: ${l.display}. Show the sentence behind it`}
                  content={
                    l.evidence ? (
                      <q>{l.evidence}</q>
                    ) : (
                      "The posting does not say this in so many words."
                    )
                  }
                  source={l.evidence ? "From the posting" : undefined}
                  triggerClassName="font-medium underline decoration-dotted underline-offset-4"
                >
                  {l.display}
                </EvidencePopover>
              </dd>
            </div>
          ))}
        </dl>
        {SKILL_LISTS.map(([key, label]) => {
          const items = job.facets[key] as string[] | undefined
          if (!items?.length) return null
          return (
            <div key={key} className="grid gap-1">
              <div className="eyebrow">{label}</div>
              <ul className="flex flex-wrap gap-1.5">
                {items.map((s) => (
                  <li key={s}>
                    <Chip tone="neutral">{s}</Chip>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </section>

      <section aria-label="Why it fits" className="grid gap-2">
        <SectionHeader title="Why it fits" />
        {fits.length > 0 ? (
          <ul className="grid gap-1.5 panel p-4">
            {fits.map((r) => (
              <li key={r.criterion}>
                <b>{r.criterion}.</b> {r.note}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            {assessments.isPending
              ? "Loading..."
              : "No strong match has been written up yet. It appears here after scoring."}
          </p>
        )}
        <SectionHeader title="Gaps" as="h3" />
        {a && a.gaps.length > 0 ? (
          <ul className="grid list-disc gap-1 pl-5">
            {a.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No gaps recorded.</p>
        )}
      </section>

      <section aria-label="One role per employer" className="grid gap-2">
        <SectionHeader title="One role per employer" />
        <div className="panel p-4">
          <ConflictStatus job={job} />
        </div>
      </section>

      <section aria-label="Tags" className="grid gap-2">
        <SectionHeader title="Tags" />
        <TagsEditor jobId={job.id} tags={job.tags} />
      </section>

      <section aria-label="Notes" className="grid gap-2">
        <SectionHeader title="Your notes" />
        <NotesEditor jobId={job.id} initial={job.notes} />
      </section>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border py-2 first:border-t-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  )
}
