import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Check, CircleHelp, History } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip, type ChipTone } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import type { JobDetail } from "../api"
import { dateText } from "../format"
import {
  acknowledgeChange,
  changeKeys,
  changesQuery,
  type ChangeKind,
  type FieldChange,
  type JobChange,
  type JobChanges,
  type Watch,
} from "./api"

export const KIND: Record<ChangeKind, { label: string; tone: ChipTone }> = {
  closed: { label: "Closed", tone: "neutral" },
  reopened: { label: "Reopened", tone: "good" },
  deadline_moved: { label: "Deadline moved", tone: "warn" },
  pay_changed: { label: "Pay changed", tone: "warn" },
  requirements_changed: { label: "Requirements changed", tone: "warn" },
  apply_method_changed: { label: "How to apply changed", tone: "info" },
  eligibility_changed: { label: "Eligibility changed", tone: "warn" },
  location_changed: { label: "Location changed", tone: "warn" },
  wording: { label: "Wording", tone: "line" },
}

const NOT_STATED = "Not stated"

/** A before/after value (any JSON) in words; null and empty are "Not stated", never "No". */
export function valueText(v: unknown): string {
  if (v == null || v === "") return NOT_STATED
  if (typeof v === "string") return v
  if (typeof v === "number" || typeof v === "boolean") return String(v)
  if (Array.isArray(v))
    return v.length ? v.map(valueText).join(", ") : NOT_STATED
  return JSON.stringify(v)
}

function Diff({ c }: { c: FieldChange }) {
  return (
    <div
      className="grid gap-1.5 text-sm sm:grid-cols-[1fr_auto_1fr] sm:items-start"
      aria-label={`${c.field}: before and after`}
    >
      <div className="rounded-md bg-danger-soft p-2">
        <span className="eyebrow">Before</span>
        <p className="whitespace-pre-wrap">{valueText(c.before)}</p>
      </div>
      <ArrowRight
        className="mt-6 hidden size-4 text-faint sm:block"
        aria-hidden="true"
      />
      <div className="rounded-md bg-good-soft p-2">
        <span className="eyebrow">After</span>
        <p className="whitespace-pre-wrap">{valueText(c.after)}</p>
      </div>
    </div>
  )
}

function ChangeRow({ c, jobId }: { c: JobChange; jobId: string }) {
  const qc = useQueryClient()
  const ack = useMutation({
    mutationFn: () => acknowledgeChange(c.id),
    onSuccess: (row) =>
      qc.setQueryData<JobChanges>(changeKeys.changes(jobId), (old) =>
        old
          ? {
              ...old,
              changes: old.changes.map((x) => (x.id === row.id ? row : x)),
            }
          : old
      ),
  })
  const seen = !!c.acknowledged_at
  return (
    <li
      data-change={c.id}
      data-material={c.material}
      data-seen={seen}
      className="grid gap-2 rounded-md border border-border bg-surface p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        {c.material ? (
          <Chip tone="warn">Material: the role was assessed again</Chip>
        ) : (
          <Chip tone="line">Wording only</Chip>
        )}
        <span className="text-xs text-faint">
          from {c.source.replace(/_/g, " ")}
        </span>
        <time className="ml-auto text-xs text-faint" dateTime={c.detected_at}>
          {dateText(c.detected_at)}
        </time>
      </div>
      <ul className="m-0 grid list-none gap-2 p-0">
        {c.changes.map((f, i) => (
          <li
            key={`${f.field}-${i}`}
            data-kind={f.kind}
            className="grid gap-1.5"
          >
            <span className="flex flex-wrap items-center gap-1.5">
              <Chip tone={KIND[f.kind].tone}>{KIND[f.kind].label}</Chip>
              {!f.material && c.material && <Chip tone="line">wording</Chip>}
              <span className="text-sm">{f.summary}</span>
            </span>
            {f.kind !== "wording" && <Diff c={f} />}
          </li>
        ))}
      </ul>
      {c.invalidated_packet_ids.length > 0 && (
        <p className="text-sm">
          The approved packet was set aside: approve a new one before anything
          is sent.
        </p>
      )}
      <div className="flex items-center gap-2">
        {seen ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Check className="size-3.5" aria-hidden="true" />
            Seen {dateText(c.acknowledged_at!)}
          </span>
        ) : (
          <Button
            size="xs"
            variant="outline"
            disabled={ack.isPending}
            onClick={() => ack.mutate()}
          >
            Mark as seen
          </Button>
        )}
        {ack.isError && (
          <span role="alert" className="text-xs text-danger">
            {ack.error.message}
          </span>
        )}
      </div>
    </li>
  )
}

const WATCH_WORDS: Record<Watch["last_result"], string> = {
  unchanged: "no change",
  changed: "changed",
  closed: "closed",
  unknown: "unknown",
}

function WatchLine({
  watch,
  lastChecked,
}: {
  watch: Watch | null | undefined
  lastChecked: string | null | undefined
}) {
  if (!watch)
    return (
      <p className="text-sm text-muted-foreground" data-watch="none">
        Not watched for changes.
        {lastChecked ? ` Last checked ${dateText(lastChecked)}.` : ""}
      </p>
    )
  return (
    <p
      className="flex flex-wrap items-center gap-1.5 text-sm"
      data-watch={watch.last_result}
    >
      {watch.last_result === "unknown" && (
        <CircleHelp className="size-4 text-warn" aria-hidden="true" />
      )}
      <span>
        Watched. Last scanned {dateText(watch.last_scanned_at)}:{" "}
        {WATCH_WORDS[watch.last_result]}.
      </span>
      {watch.last_result === "unknown" && (
        <span>
          We couldn't check the posting, so whether it is still open is{" "}
          <b>unknown</b>. It has not been marked closed.
        </span>
      )}
      {watch.note && (
        <span className="text-muted-foreground">{watch.note}</span>
      )}
    </p>
  )
}

/** An unseen material change that set aside an approved packet (links to the Studio). */
export function StalePacketBanner({ jobId }: { jobId: string }) {
  const q = useQuery(changesQuery(jobId))
  const stale = q.data?.changes.find(
    (c) =>
      c.material && !c.acknowledged_at && c.invalidated_packet_ids.length > 0
  )
  if (!stale) return null
  const appId = stale.application_ids[0]
  return (
    <div
      role="alert"
      data-banner="stale-packet"
      className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-warn bg-warn-soft px-3 py-2 text-sm"
    >
      <span className="font-semibold text-warn">
        The posting changed after you approved the packet.
      </span>
      <span>
        {stale.changes
          .filter((f) => f.material)
          .map((f) => f.summary)
          .join("; ")}
      </span>
      {appId && (
        <Button asChild size="xs" className="ml-auto">
          <Link to="/studio" search={{ application: appId }}>
            Review in the Studio
          </Link>
        </Button>
      )}
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
  const items = [...q.data.changes].sort((a, b) =>
    b.detected_at.localeCompare(a.detected_at)
  )
  return (
    <div className="grid gap-4">
      <SectionHeader title="Posting changes" />
      <WatchLine watch={q.data.watch} lastChecked={job.last_checked_at} />
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
            <ChangeRow key={c.id} c={c} jobId={job.id} />
          ))}
        </ol>
      )}
    </div>
  )
}
