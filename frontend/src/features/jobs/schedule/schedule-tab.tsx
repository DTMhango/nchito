import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, CalendarPlus, Download } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { meQuery } from "@/lib/api/endpoints"
import type { JobDetail } from "../api"
import {
  cancelEvent,
  icsUrl,
  jobEventsQuery,
  scheduleKeys,
  type EventOut,
} from "./api"
import { DebriefForm, OUTCOME_LABEL } from "./debrief-form"
import { EventForm, type FormMode } from "./event-form"
import { ConflictWarning, EventTimes } from "./event-times"
import { STATUS_LABEL, TYPE_LABEL } from "./format"
import { ProposalConfirm } from "./proposal"
import { ThankYouOffer } from "./round-links"

type Editing = { mode: FormMode; event: EventOut | null }

/** The job's interview schedule: add, edit, reschedule, cancel, debrief, and confirm proposals. */
export function ScheduleTab({ job }: { job: JobDetail }) {
  const q = useQuery(jobEventsQuery(job.id))
  const me = useQuery(meQuery())
  const [editing, setEditing] = useState<Editing | null>(null)
  const zone = me.data?.timezone ?? "Africa/Lusaka"
  const events = q.data ?? []

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="max-w-[70ch] text-sm text-muted-foreground">
          Interviews for this role. Times show in their zone and yours. An
          interview proposed from an email is not on your calendar until you
          confirm it.
        </p>
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => setEditing({ mode: "new", event: null })}
        >
          <CalendarPlus aria-hidden="true" />
          Add interview
        </Button>
      </div>

      {editing?.mode === "new" && (
        <EventForm
          mode="new"
          jobId={job.id}
          event={null}
          defaultZone={zone}
          onDone={() => setEditing(null)}
          onCancel={() => setEditing(null)}
        />
      )}

      {q.isPending ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : q.isError ? (
        <p role="alert" className="text-danger">
          Could not load the schedule. Reload to try again.
        </p>
      ) : events.length === 0 && !editing ? (
        <EmptyState
          icon={CalendarDays}
          title="No interviews yet"
          description="Add one when you are invited, or approve a proposal that arrives by email."
        />
      ) : (
        <ul aria-label="Interviews" className="grid gap-3">
          {events.map((e) => (
            <li key={e.id}>
              <EventCard
                event={e}
                job={job}
                zone={zone}
                editing={editing?.event?.id === e.id ? editing : null}
                onEdit={(mode) => setEditing({ mode, event: e })}
                onClose={() => setEditing(null)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function EventCard({
  event: e,
  job,
  zone,
  editing,
  onEdit,
  onClose,
}: {
  event: EventOut
  job: JobDetail
  zone: string
  editing: Editing | null
  onEdit: (mode: FormMode) => void
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [debrief, setDebrief] = useState(false)
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const cancel = useMutation({
    mutationFn: () => cancelEvent(e.id),
    onSuccess: () => {
      toast.success("Interview cancelled")
      setConfirmingCancel(false)
      void qc.invalidateQueries({ queryKey: scheduleKeys.job(job.id) })
      void qc.invalidateQueries({ queryKey: scheduleKeys.upcoming })
    },
  })
  const proposed = e.status === "proposed"
  const live = e.status === "confirmed" || proposed

  return (
    <article
      aria-label={`Round ${e.round_number}, ${TYPE_LABEL[e.type]}`}
      data-status={e.status}
      className="grid gap-2.5 panel p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <b>Round {e.round_number}</b>
        <span className="text-sm text-muted-foreground">
          {TYPE_LABEL[e.type]}
        </span>
        <Chip
          tone={
            proposed
              ? "warn"
              : e.status === "confirmed"
                ? "good"
                : e.status === "cancelled"
                  ? "line"
                  : "neutral"
          }
        >
          {STATUS_LABEL[e.status]}
        </Chip>
        {e.outcome && <Chip tone="info">{OUTCOME_LABEL[e.outcome]}</Chip>}
        {e.google_synced && <Chip tone="line">On Google Calendar</Chip>}
      </div>

      {proposed && (
        <p
          role="note"
          className="rounded-sm bg-warn-soft px-3 py-2 text-sm text-warn"
        >
          Proposed from an email, not confirmed.
          {e.needs_input && " It needs a time from you before it can be."}
        </p>
      )}

      {!(proposed && e.candidates.length > 0) && <EventTimes event={e} />}
      {live && <ConflictWarning event={e} />}

      {(e.location || e.meeting_link || e.interviewers.length > 0) && (
        <p className="text-sm text-muted-foreground">
          {e.location}
          {e.location && e.meeting_link && " · "}
          {e.meeting_link && /^https?:\/\//.test(e.meeting_link) && (
            <a
              className="text-primary-ink underline"
              href={e.meeting_link}
              target="_blank"
              rel="noreferrer noopener"
            >
              Meeting link
            </a>
          )}
          {e.interviewers.length > 0 && (
            <>
              {(e.location || e.meeting_link) && " · "}
              With {e.interviewers.join(", ")}
            </>
          )}
        </p>
      )}
      {e.notes && <p className="text-sm">{e.notes}</p>}
      {e.google_error && (
        <p className="text-sm text-warn">
          Google Calendar did not update: {e.google_error}
        </p>
      )}

      {proposed && <ProposalConfirm event={e} jobId={job.id} />}

      {editing && editing.mode !== "new" && (
        <EventForm
          mode={editing.mode}
          jobId={job.id}
          event={e}
          defaultZone={zone}
          onDone={onClose}
          onCancel={onClose}
        />
      )}
      {debrief && (
        <DebriefForm
          event={e}
          jobId={job.id}
          onDone={() => setDebrief(false)}
          onCancel={() => setDebrief(false)}
        />
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        {e.debrief_due && !e.outcome && (
          <Chip tone="accent">Waiting for your debrief</Chip>
        )}
        {e.status !== "cancelled" && !e.outcome && !proposed && (
          <Button size="sm" variant="outline" onClick={() => setDebrief(true)}>
            How did it go?
          </Button>
        )}
        {live && (
          <>
            <Button size="sm" variant="ghost" onClick={() => onEdit("edit")}>
              Edit
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onEdit("reschedule")}
            >
              Reschedule
            </Button>
            {confirmingCancel ? (
              <>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={cancel.isPending}
                  onClick={() => cancel.mutate()}
                >
                  Yes, cancel it
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConfirmingCancel(false)}
                >
                  Keep it
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirmingCancel(true)}
              >
                Cancel interview
              </Button>
            )}
          </>
        )}
        {e.status === "confirmed" && (
          <Button asChild size="sm" variant="ghost">
            <a href={icsUrl(e.id)} download>
              <Download aria-hidden="true" />
              Add to calendar (.ics)
            </a>
          </Button>
        )}
        {e.status === "done" && e.outcome !== "did_not_happen" && (
          <ThankYouOffer event={e} />
        )}
        <Button asChild size="sm" variant="ghost" className="ml-auto">
          <Link
            to="/jobs/$id"
            params={{ id: job.id }}
            search={{ tab: "interview", round: e.round_number }}
          >
            Prepare round {e.round_number}
          </Link>
        </Button>
      </div>
    </article>
  )
}
