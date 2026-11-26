import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import {
  draftFollowup,
  followupKeys,
  followupNotNeeded,
  followupsQuery,
  snoozeFollowup,
  type FollowupItem,
} from "./api"

const STATUS: Record<
  FollowupItem["status"],
  { label: string; tone: "warn" | "info" | "neutral" | "good" }
> = {
  upcoming: { label: "Coming up", tone: "neutral" },
  due: { label: "Due", tone: "warn" },
  snoozed: { label: "Snoozed", tone: "info" },
  drafted: { label: "Drafted", tone: "info" },
  not_needed: { label: "Not needed", tone: "neutral" },
  sent: { label: "Sent", tone: "good" },
}

const when = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  })

/** Follow-ups after no reply: due, snoozed, drafted and coming up. Drafts wait for approval. */
export function FollowupsPage() {
  const qc = useQueryClient()
  const q = useQuery(followupsQuery())
  const refresh = () => qc.invalidateQueries({ queryKey: followupKeys.due })
  const act = useMutation({
    mutationFn: ({
      appId,
      action,
    }: {
      appId: string
      action: "draft" | "snooze" | "not_needed"
    }): Promise<unknown> =>
      action === "draft"
        ? draftFollowup(appId)
        : action === "snooze"
          ? snoozeFollowup(appId)
          : followupNotNeeded(appId),
    onSuccess: refresh,
  })

  return (
    <div>
      <PageHeader
        title="Follow-ups"
        description="Applications with no reply, by when a follow-up is due. A draft is never sent without your approval."
        meta={
          q.data ? (
            <Chip tone={q.data.auto_send ? "info" : "neutral"}>
              {q.data.auto_send
                ? "Plain follow-ups go automatically"
                : "Every follow-up waits for you"}
            </Chip>
          ) : null
        }
      />
      {q.isPending && <p className="text-muted-foreground">Loading...</p>}
      {q.isError && <p role="alert">{q.error.message}</p>}
      {q.data && q.data.items.length === 0 && (
        <EmptyState
          title="Nothing to follow up"
          description="No application is waiting on a reply."
        />
      )}
      {q.data && q.data.items.length > 0 && (
        <ul className="panel p-0" aria-label="Follow-ups">
          {q.data.items.map((i) => (
            <li
              key={`${i.application_id}-${i.sequence}`}
              aria-label={`${i.title} at ${i.employer}`}
              className="flex flex-wrap items-center gap-2 border-t border-border row-pad first:border-t-0"
            >
              <div className="min-w-0 flex-1">
                <Link
                  to="/jobs/$id"
                  params={{ id: i.job_id }}
                  search={{ tab: "messages" }}
                  className="font-semibold"
                >
                  {i.title} at {i.employer}
                </Link>
                <p className="text-sm text-muted-foreground">
                  Follow-up {i.sequence} · {i.stage} ·{" "}
                  {i.status === "snoozed" ? "until" : "due"} {when(i.due_at)}
                </p>
              </div>
              <Chip tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Chip>
              {i.status !== "drafted" && (
                <Button
                  size="sm"
                  disabled={act.isPending}
                  onClick={() =>
                    act.mutate({ appId: i.application_id, action: "draft" })
                  }
                >
                  Draft
                </Button>
              )}
              {(i.status === "due" || i.status === "upcoming") && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    act.mutate({ appId: i.application_id, action: "snooze" })
                  }
                >
                  Snooze
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  act.mutate({ appId: i.application_id, action: "not_needed" })
                }
              >
                Not needed
              </Button>
            </li>
          ))}
        </ul>
      )}
      {act.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {act.error.message}
        </p>
      )}
    </div>
  )
}
