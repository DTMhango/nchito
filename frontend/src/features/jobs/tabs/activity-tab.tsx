import { useQuery } from "@tanstack/react-query"
import { Activity } from "lucide-react"
import { EmptyState } from "@/components/empty-state"
import { jobAuditQuery, timelineQuery, type JobDetail } from "../api"

type Entry = { id: string; at: string; actor: string; what: string; reason?: string }

const reasonOf = (d: Record<string, unknown>) =>
  typeof d.reason === "string" ? d.reason : typeof d.note === "string" ? d.note : undefined

/** Timeline plus audit trail for this role, newest first, each with who did it and why. */
export function ActivityTab({ job }: { job: JobDetail }) {
  const tl = useQuery(timelineQuery(job.application_id))
  const audit = useQuery(jobAuditQuery(job.id))
  const entries: Entry[] = [
    ...(tl.data ?? []).map((e) => ({
      id: `t-${e.id}`,
      at: e.created_at,
      actor: e.actor,
      what: e.kind.replaceAll("_", " "),
      reason: reasonOf(e.detail),
    })),
    ...(audit.data ?? []).map((e) => ({
      id: `a-${e.id}`,
      at: e.created_at,
      actor: e.actor,
      what: e.action.replaceAll(".", " "),
      reason: reasonOf(e.detail),
    })),
  ].sort((a, b) => b.at.localeCompare(a.at))

  if (tl.isPending || audit.isPending)
    return <p className="text-muted-foreground">Loading...</p>
  if (entries.length === 0)
    return (
      <EmptyState
        icon={Activity}
        title="Nothing has happened yet"
        description="Every stage change, edit, approval, agent step and email for this role shows here, with who did it."
      />
    )
  return (
    <ol aria-label="Timeline" className="panel p-4">
      {entries.map((e) => (
        <li key={e.id} className="grid gap-0.5 border-t border-border row-pad first:border-t-0">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <b className="capitalize">{e.what}</b>
            <span className="text-sm text-muted-foreground">by {e.actor}</span>
            <span className="num ml-auto text-xs text-faint">
              {new Date(e.at).toLocaleString()}
            </span>
          </div>
          {e.reason && <p className="text-sm text-muted-foreground">Reason: {e.reason}</p>}
        </li>
      ))}
    </ol>
  )
}
