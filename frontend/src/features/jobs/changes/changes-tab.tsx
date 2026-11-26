import { Link } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { ArrowRight, CircleHelp, History } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip, type ChipTone } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import type { JobDetail } from "../api"
import { dateText } from "../format"
import type { PostingChange, PostingChangeKind } from "../w3-pending-types"
import { changesQuery } from "./api"

export const KIND: Record<
  PostingChangeKind,
  { label: string; tone: ChipTone }
> = {
  closed: { label: "Closed", tone: "neutral" },
  deadline_moved: { label: "Deadline moved", tone: "warn" },
  pay_changed: { label: "Pay changed", tone: "warn" },
  requirements_changed: { label: "Requirements changed", tone: "warn" },
  method_changed: { label: "How to apply changed", tone: "info" },
  check_failed: { label: "Couldn't check", tone: "line" },
}

const NOT_STATED = "Not stated"

function Diff({ c }: { c: PostingChange }) {
  if (c.before == null && c.after == null) return null
  return (
    <div
      className="grid gap-1.5 text-sm sm:grid-cols-[1fr_auto_1fr] sm:items-start"
      aria-label={`${c.field ?? "Value"}: before and after`}
    >
      <div className="rounded-md bg-danger-soft p-2">
        <span className="eyebrow">Before</span>
        <p className="whitespace-pre-wrap">{c.before ?? NOT_STATED}</p>
      </div>
      <ArrowRight
        className="mt-6 hidden size-4 text-faint sm:block"
        aria-hidden="true"
      />
      <div className="rounded-md bg-good-soft p-2">
        <span className="eyebrow">After</span>
        <p className="whitespace-pre-wrap">{c.after ?? NOT_STATED}</p>
      </div>
    </div>
  )
}

function ChangeRow({ c }: { c: PostingChange }) {
  const k = KIND[c.kind]
  return (
    <li
      data-change={c.kind}
      className="grid gap-2 rounded-md border border-border bg-surface p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Chip
          tone={k.tone}
          icon={c.kind === "check_failed" ? CircleHelp : undefined}
        >
          {k.label}
        </Chip>
        {c.material ? (
          <Chip tone="warn">Material: the role was assessed again</Chip>
        ) : (
          c.kind !== "check_failed" && <Chip tone="line">Wording only</Chip>
        )}
        <time className="ml-auto text-xs text-faint" dateTime={c.at}>
          {dateText(c.at)}
        </time>
      </div>
      {c.kind === "check_failed" ? (
        <p className="text-sm">
          We couldn't check this posting, so whether it is still open is{" "}
          <b>unknown</b>. It has not been marked closed.
          {c.note ? ` ${c.note}` : ""}
        </p>
      ) : (
        <>
          {c.note && <p className="text-sm">{c.note}</p>}
          <Diff c={c} />
        </>
      )}
    </li>
  )
}

/** When an approved packet was built on a posting that has since changed (links to the Studio). */
export function StalePacketBanner({ jobId }: { jobId: string }) {
  const q = useQuery(changesQuery(jobId))
  const stale = q.data?.stale_packet
  if (!stale) return null
  return (
    <div
      role="alert"
      data-banner="stale-packet"
      className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-warn bg-warn-soft px-3 py-2 text-sm"
    >
      <span className="font-semibold text-warn">
        The posting changed after you approved the packet.
      </span>
      <span>{stale.reason}</span>
      <Button asChild size="xs" className="ml-auto">
        <Link to="/studio" search={{ application: stale.application_id }}>
          Review in the Studio
        </Link>
      </Button>
    </div>
  )
}

export function ChangesTab({ job }: { job: JobDetail }) {
  const q = useQuery(changesQuery(job.id))
  if (q.isPending) return <p className="text-muted-foreground">Loading...</p>
  if (q.isError)
    return (
      <p role="alert" className="text-danger">
        Couldn't load the changes. {q.error.message}
      </p>
    )
  const items = [...q.data.items].sort((a, b) => b.at.localeCompare(a.at))
  return (
    <div className="grid gap-4">
      <SectionHeader
        title="Posting changes"
        aside={
          job.last_checked_at
            ? `Last checked ${dateText(job.last_checked_at)}`
            : "Not checked since it was captured"
        }
      />
      {items.length === 0 ? (
        <EmptyState
          icon={History}
          title="No changes seen"
          description="Each time the posting is checked, a change to its status, deadline, pay, requirements or way to apply shows up here with before and after."
        />
      ) : (
        <ol
          aria-label="Changes, newest first"
          className="m-0 grid list-none gap-2 p-0"
        >
          {items.map((c) => (
            <ChangeRow key={c.id} c={c} />
          ))}
        </ol>
      )}
    </div>
  )
}
