import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { View } from "@/components/view"
import { heldRolesQuery, approvalQueueQuery } from "@/features/autopilot/api"
import { CHANNEL_LABEL } from "@/features/autopilot/logic"

/** Everything ready for a decision, and the roles held back at the same employers. */
export function ApprovalsPage() {
  const queue = useQuery(approvalQueueQuery())
  const held = useQuery(heldRolesQuery())
  const items = queue.data ?? []
  return (
    <View className="grid content-start gap-5">
      <section aria-label="Waiting for your approval" className="grid gap-2.5">
        <SectionHeader
          title="Waiting for your approval"
          aside="Nothing is sent until you approve it, or every automatic check passes."
        />
        {queue.isSuccess && items.length === 0 && (
          <EmptyState
            title="Nothing to approve"
            description="Prepared applications appear here when they are ready."
          />
        )}
        <ul className="grid gap-2">
          {items.map((a) => (
            <li key={a.id}>
              <Link
                to="/approvals/$applicationId"
                params={{ applicationId: a.id }}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-3 hover:border-border-strong"
              >
                <span className="text-md font-semibold">{a.title}</span>
                <span className="text-muted-foreground">{a.employer}</span>
                {a.channel && (
                  <Chip tone="line">{CHANNEL_LABEL[a.channel]}</Chip>
                )}
                {a.score !== null && (
                  <span className="ml-auto num text-sm text-faint">
                    Score {a.score}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      </section>
      {(held.data?.length ?? 0) > 0 && (
        <section aria-label="Held roles" className="grid gap-2.5">
          <SectionHeader
            title="Held back"
            aside="Another role at the same employer outranks these, so they are not prepared or sent."
          />
          <ul className="grid gap-1.5">
            {held.data?.map((j) => (
              <li
                key={j.id}
                className="grid gap-0.5 rounded-md border border-border bg-surface px-3 py-2 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone="warn">Held</Chip>
                  <Link
                    to="/jobs/$id"
                    params={{ id: j.id }}
                    className="font-medium hover:underline"
                  >
                    {j.title}
                  </Link>
                  <span className="text-muted-foreground">{j.employer}</span>
                </div>
                <p className="text-muted-foreground">
                  {j.conflict?.outranked_by_title
                    ? `Winner: ${j.conflict.outranked_by_title}, ${j.conflict.outranked_by_score ?? "?"} vs ${j.conflict.score ?? j.best_score ?? "?"}.`
                    : (j.conflict_note ?? "Outranked by another role here.")}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </View>
  )
}
