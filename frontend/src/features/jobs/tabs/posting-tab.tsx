import { ExternalLink, FileClock } from "lucide-react"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import type { JobDetail } from "../api"
import { dateText } from "../format"

const LIVE = {
  open: { label: "Still open", tone: "good" },
  closed: { label: "Closed", tone: "neutral" },
  unknown: { label: "Not checked", tone: "warn" },
} as const

export function PostingTab({ job }: { job: JobDetail }) {
  const live = LIVE[job.availability]
  return (
    <div className="grid gap-7">
      <section aria-label="Live status" className="flex flex-wrap items-center gap-2">
        <Chip tone={live.tone}>{live.label}</Chip>
        <span className="text-sm text-muted-foreground">
          {job.last_checked_at
            ? `Last checked ${dateText(job.last_checked_at)}`
            : "Not checked since it was captured"}
        </span>
        {job.repost_of_id && <Chip tone="info">A repost</Chip>}
      </section>

      <section aria-label="Captured text" className="grid gap-2">
        <SectionHeader title="The posting as captured" />
        {job.raw_text ? (
          <pre className="max-h-[60vh] overflow-auto rounded-md bg-paper p-4 text-sm leading-relaxed whitespace-pre-wrap text-paper-ink">
            {job.raw_text}
          </pre>
        ) : (
          <p className="text-sm text-muted-foreground">
            The full text has been dropped under your retention setting. A minimal
            record is kept.
          </p>
        )}
      </section>

      <section aria-label="Sightings" className="grid gap-2">
        <SectionHeader title="Where it was seen" aside={`${job.sightings.length} link${job.sightings.length === 1 ? "" : "s"}`} />
        <ul className="panel p-4">
          {job.sightings.map((s) => (
            <li key={s.url} className="grid gap-0.5 border-t border-border row-pad first:border-t-0">
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 break-all text-primary-ink underline"
              >
                {s.url}
                <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
              </a>
              <span className="text-xs text-faint">
                First seen {dateText(s.first_seen_at)}, last seen {dateText(s.last_seen_at)}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Change history" className="grid gap-2">
        <SectionHeader title="Change history" />
        <div className="rounded-lg border border-dashed border-border-strong">
          <EmptyState
            icon={FileClock}
            title="Changes will be listed here"
            description="If the posting is edited or reposted, each change shows field by field, for example Remote worldwide to UK residents only, with the date it was noticed. This arrives in wave 3."
          />
        </div>
      </section>
    </div>
  )
}
