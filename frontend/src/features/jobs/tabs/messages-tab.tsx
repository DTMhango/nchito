import { useQuery } from "@tanstack/react-query"
import { Mail } from "lucide-react"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { mailThreadsQuery, type JobDetail, type MailThread } from "../api"
import { dateText } from "../format"

const CLASS: Record<
  MailThread["classification"],
  { label: string; tone: "good" | "danger" | "info" | "warn" | "line" }
> = {
  confirmation: { label: "Confirmation", tone: "good" },
  rejection: { label: "Rejection", tone: "danger" },
  interview: { label: "Interview", tone: "info" },
  information_request: { label: "They ask for information", tone: "warn" },
  other: { label: "Other", tone: "line" },
}

/**
 * Email linked to this role. Subjects and senders come from outside, so they render as plain
 * text. A linked thread only proposes a stage change: it waits as a pending action.
 */
export function MessagesTab({ job }: { job: JobDetail }) {
  const threads = useQuery(mailThreadsQuery(job.application_id))

  if (!job.application_id)
    return (
      <EmptyState
        icon={Mail}
        title="No application yet"
        description="Email about this role appears here once there is an application to link it to."
      />
    )
  if (threads.isPending)
    return <p className="text-muted-foreground">Loading...</p>
  if (threads.isError)
    return (
      <EmptyState
        title="Could not load the email"
        description={threads.error.message}
      />
    )

  return (
    <section aria-label="Mail threads" className="grid gap-2">
      <SectionHeader title="Email about this role" />
      <p className="text-sm text-muted-foreground">
        Linking a thread never changes the stage on its own: it proposes the
        change, and the proposal waits for you under pending actions.
      </p>
      {threads.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No email is linked to this application yet.
        </p>
      ) : (
        <ul className="panel p-0" aria-label="Threads">
          {threads.data.map((t) => (
            <ThreadRow key={t.id} thread={t} />
          ))}
        </ul>
      )}
    </section>
  )
}

function ThreadRow({ thread: t }: { thread: MailThread }) {
  const c = CLASS[t.classification]
  return (
    <li
      data-classification={t.classification}
      className="grid gap-1 border-t border-border row-pad first:border-t-0"
    >
      <div className="flex flex-wrap items-center gap-2">
        <b className="min-w-0 flex-1 font-semibold break-words">
          {t.subject ?? "(no subject)"}
        </b>
        <Chip tone={c.tone}>{c.label}</Chip>
        {t.needs_review && <Chip tone="warn">Check the link</Chip>}
      </div>
      <div className="flex flex-wrap gap-x-3 text-sm text-muted-foreground">
        <span>From {t.sender ?? "an unknown sender"}</span>
        <span>
          {t.last_message_at
            ? `Last message ${dateText(t.last_message_at)}`
            : "No messages read yet"}
        </span>
      </div>
    </li>
  )
}
