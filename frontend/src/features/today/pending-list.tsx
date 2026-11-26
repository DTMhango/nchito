import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Bell } from "lucide-react"
import { EmptyState } from "@/components/empty-state"
import { pendingQuery, type PendingAction } from "@/features/applications/api"
import { isHandoff } from "@/features/accounts/logic"
import { changeJobId, changeKind, deadlineText, urgency } from "./decisions"
import { cn } from "@/lib/utils"

const STRIPE = {
  danger: "bg-danger",
  warn: "bg-warn",
  info: "bg-info",
} as const

/** Open pending actions for the bell: the same items as "Needs you", newest first. */
export function usePendingActions() {
  const q = useQuery(pendingQuery())
  const items = [...(q.data?.items ?? [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at)
  )
  return { ...q, items }
}

export function PendingList({
  items,
  onNavigate,
}: {
  items: PendingAction[]
  onNavigate?: () => void
}) {
  if (items.length === 0)
    return (
      <EmptyState
        icon={Bell}
        title="Nothing new"
        description="Approvals, sign-in requests, new questions and replies from employers will show up here, newest first."
      />
    )
  return (
    <>
      <ul className="max-h-[360px] overflow-y-auto">
        {items.map((a) => (
          <li key={a.id} className="border-b border-border last:border-b-0">
            <PendingLink action={a} onNavigate={onNavigate}>
              <span
                aria-hidden="true"
                className={cn("rounded-full", STRIPE[urgency(a.deadline)])}
              />
              <span className="min-w-0">
                <span className="block text-[0.92rem] font-semibold">
                  {a.title}
                </span>
                {a.deadline && (
                  <span className="block text-xs text-muted-foreground">
                    {deadlineText(a.deadline)}
                  </span>
                )}
              </span>
            </PendingLink>
          </li>
        ))}
      </ul>
      <div className="border-t border-border px-3.5 py-2 text-sm">
        <Link to="/today" onClick={onNavigate}>
          Answer them on Today
        </Link>
      </div>
    </>
  )
}

const ROW =
  "grid grid-cols-[4px_minmax(0,1fr)] gap-3 px-3.5 py-2.5 text-foreground no-underline hover:bg-sunken"

/** Where one item opens: a blocker's handoff, a posting change's Changes tab, else Today. */
function PendingLink({
  action: a,
  onNavigate,
  children,
}: {
  action: PendingAction
  onNavigate?: () => void
  children: ReactNode
}) {
  const jobId = changeJobId(a)
  if (isHandoff(a))
    return (
      <Link
        to="/accounts/handoff/$actionId"
        params={{ actionId: a.id }}
        onClick={onNavigate}
        className={ROW}
      >
        {children}
      </Link>
    )
  if (jobId && changeKind(a))
    return (
      <Link
        to="/jobs/$id"
        params={{ id: jobId }}
        search={{ tab: "changes" }}
        onClick={onNavigate}
        className={ROW}
      >
        {children}
      </Link>
    )
  return (
    <Link
      to="/today"
      search={{ action: a.id }}
      onClick={onNavigate}
      className={ROW}
    >
      {children}
    </Link>
  )
}
