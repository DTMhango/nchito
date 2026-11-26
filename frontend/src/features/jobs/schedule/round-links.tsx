/** Links between interview rounds (pack, mock interview) and the schedule's events, in both directions.
 * A round and an event belong together when they are the same job's same round number. */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { CalendarDays, MailPlus } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  createMessage,
  followupKeys,
  messagesQuery,
} from "@/features/followups/api"
import { jobEventsQuery, type EventOut } from "./api"
import { wallText } from "./format"

const TYPE_TEXT: Record<EventOut["type"], string> = {
  phone: "phone",
  video: "video",
  onsite: "on site",
  assessment: "assessment",
}

/** The events that still stand for a round (not cancelled or replaced), soonest first. */
export function eventsForRound(
  events: EventOut[] | undefined,
  round: number
): EventOut[] {
  return (events ?? [])
    .filter(
      (e) =>
        e.round_number === round &&
        e.status !== "cancelled" &&
        e.status !== "rescheduled"
    )
    .sort((a, b) => (a.starts_at ?? "").localeCompare(b.starts_at ?? ""))
}

function when(e: EventOut): string {
  return e.owner_starts_local ? wallText(e.owner_starts_local) : "time not set"
}

/** Pack side: the rounds on the schedule, each linking to the Schedule tab. */
export function ScheduledRounds({ jobId }: { jobId: string }) {
  const events = useQuery(jobEventsQuery(jobId))
  const rounds = [
    ...new Set(
      (events.data ?? [])
        .filter((e) => e.status !== "cancelled" && e.status !== "rescheduled")
        .map((e) => e.round_number)
    ),
  ].sort((a, b) => a - b)
  if (rounds.length === 0) return null
  return (
    <nav
      aria-label="Rounds on your schedule"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
    >
      <CalendarDays className="size-4 text-faint" aria-hidden="true" />
      {rounds.map((n) => {
        const e = eventsForRound(events.data, n)[0]
        return (
          <Link
            key={n}
            to="/jobs/$id"
            params={{ id: jobId }}
            search={{ tab: "schedule" }}
            className="text-primary-ink underline"
          >
            Round {n}, {TYPE_TEXT[e.type]}: {when(e)}
            {e.status === "done" ? " (done)" : ""}
          </Link>
        )
      })}
    </nav>
  )
}

/** Mock interview side: the selected round's event on the schedule, or a way to add one. */
export function RoundEventLink({
  jobId,
  round,
}: {
  jobId: string
  round: number
}) {
  const events = useQuery(jobEventsQuery(jobId))
  if (events.isPending) return null
  const e = eventsForRound(events.data, round)[0]
  return (
    <p className="text-sm text-muted-foreground">
      {e ? `Round ${round} is on your schedule: ${when(e)}. ` : ""}
      <Link
        to="/jobs/$id"
        params={{ id: jobId }}
        search={{ tab: "schedule" }}
        className="text-primary-ink underline"
      >
        {e ? "Open the schedule" : `Add round ${round} to your schedule`}
      </Link>
    </p>
  )
}

/** After an interview is marked done: offer a thank-you message (a draft the owner checks and approves). */
export function ThankYouOffer({ event }: { event: EventOut }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const messages = useQuery(messagesQuery(event.application_id))
  const since = event.starts_at ?? event.updated_at
  const existing = messages.data?.messages.find(
    (m) =>
      m.kind === "thank_you" &&
      m.status !== "discarded" &&
      m.created_at >= since
  )
  const draft = useMutation({
    mutationFn: () =>
      createMessage(event.application_id, {
        kind: "thank_you",
        note: `Thank them for the round ${event.round_number} interview${
          event.interviewers.length
            ? ` with ${event.interviewers.join(", ")}`
            : ""
        }.`,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({
        queryKey: followupKeys.messages(event.application_id),
      })
      toast.success("Thank-you drafted. Check it before it goes.")
      void navigate({
        to: "/jobs/$id",
        params: { id: event.job_id },
        search: { tab: "messages" },
      })
    },
    onError: (e) => toast.error(e.message),
  })
  if (messages.isPending) return null
  if (existing)
    return (
      <Link
        to="/jobs/$id"
        params={{ id: event.job_id }}
        search={{ tab: "messages" }}
        className="text-sm text-primary-ink underline"
      >
        Thank-you {existing.status === "draft" ? "drafted" : "approved"}
      </Link>
    )
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={draft.isPending}
      onClick={() => draft.mutate()}
    >
      <MailPlus aria-hidden="true" /> Draft a thank-you
    </Button>
  )
}
