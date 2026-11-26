import { useQuery } from "@tanstack/react-query"
import { Send } from "lucide-react"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import { applicationQuery, pendingActionsQuery, type JobDetail } from "../api"
import { dateText } from "../format"
import { dispatchesQuery } from "@/features/autopilot/api"
import { CHANNEL_LABEL, dispatchView } from "@/features/autopilot/logic"
import { meQuery } from "@/lib/api/endpoints"

export function ApplicationTab({ job }: { job: JobDetail }) {
  const app = useQuery(applicationQuery(job.application_id))
  const pending = useQuery(pendingActionsQuery())

  if (!job.application_id)
    return (
      <EmptyState
        icon={Send}
        title="Not applied yet"
        description="Once an application exists, this shows the channel, the answers given on the form, the confirmation evidence and anything still waiting for you."
      />
    )
  if (app.isPending) return <p className="text-muted-foreground">Loading...</p>
  if (!app.data)
    return (
      <EmptyState
        title="Could not load the application"
        description="Try again in a moment."
      />
    )

  const a = app.data
  const open = (pending.data ?? []).filter((p) => p.application_id === a.id)
  const snap = a.submitted_snapshot

  return (
    <div className="grid gap-7">
      <section aria-label="Channel" className="grid gap-2">
        <SectionHeader title="How it was applied" />
        <dl className="grid gap-2 panel p-4 sm:grid-cols-2">
          <Row label="Channel" value={a.channel ?? "Not chosen yet"} />
          <Row
            label="Applied on"
            value={a.applied_at ? dateText(a.applied_at) : "Not applied yet"}
          />
          <Row
            label="Applied by"
            value={
              a.applied_outside ? "You, outside the app" : "Through the app"
            }
          />
          <Row label="Next step" value={a.next_step ?? "None"} />
        </dl>
      </section>

      <Sends applicationId={a.id} />

      <section aria-label="Answers given" className="grid gap-2">
        <SectionHeader title="Answers given on the form" />
        {snap && snap.answers.length > 0 ? (
          <dl className="grid gap-2 panel p-4">
            {snap.answers.map((x) => (
              <div key={x.question} className="grid gap-0.5">
                <dt className="text-sm text-muted-foreground">
                  {x.question} {x.material && <Chip tone="warn">Material</Chip>}
                </dt>
                <dd>{x.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            No answers recorded. They appear here once the application is sent.
          </p>
        )}
      </section>

      <section aria-label="Confirmation" className="grid gap-2">
        <SectionHeader title="Confirmation evidence" />
        {a.confirmation_evidence.length > 0 ? (
          <ul className="grid gap-1.5 panel p-4">
            {a.confirmation_evidence.map((e, i) => (
              <li key={i} className="text-sm">
                <Chip tone="good">{e.kind.replaceAll("_", " ")}</Chip> {e.value}
                {e.at && (
                  <span className="text-faint"> · {dateText(e.at)}</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Nothing confirms this yet. A sent application stays unconfirmed
            until a page, reference or email says otherwise.
          </p>
        )}
      </section>

      <section aria-label="Waiting for you" className="grid gap-2">
        <SectionHeader title="Open pending actions" />
        {open.length > 0 ? (
          <ul className="panel p-4">
            {open.map((p) => (
              <li
                key={p.id}
                className="border-t border-border row-pad first:border-t-0"
              >
                <b>{p.title}</b>
                {p.deadline && (
                  <span className="text-sm text-faint">
                    {" "}
                    · by {dateText(p.deadline)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Nothing is waiting for you.
          </p>
        )}
      </section>
    </div>
  )
}

/** Each send attempt and what it means; a quiet-hours hold comes from the dispatch itself. */
function Sends({ applicationId }: { applicationId: string }) {
  const q = useQuery(dispatchesQuery(applicationId))
  const tz = useQuery(meQuery()).data?.timezone
  const list = q.data ?? []
  if (list.length === 0) return null
  return (
    <section aria-label="Sends" className="grid gap-2">
      <SectionHeader title="Sends" />
      <ul className="grid gap-1.5 panel p-4">
        {list.map((d) => {
          const v = dispatchView(d, tz)
          return (
            <li
              key={d.id}
              data-kind={v.kind}
              className="grid gap-0.5 border-t border-border py-2 text-sm first:border-t-0"
            >
              <span className="flex flex-wrap items-center gap-2">
                <Chip tone={v.tone}>{v.label}</Chip>
                <span className="font-medium">{CHANNEL_LABEL[d.channel]}</span>
                <span className="text-faint">{dateText(d.created_at)}</span>
              </span>
              <span className="text-muted-foreground">{v.explain}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="eyebrow">{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}
