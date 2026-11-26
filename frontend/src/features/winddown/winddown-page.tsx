import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Chip } from "@/components/chip"
import { PageHeader, SectionHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { View } from "@/components/view"
import {
  chooseWindDown,
  followupKeys,
  reopenWindDown,
  startWindDown,
  WIND_DOWN_SENDING,
  WIND_DOWN_SUMMARY_URL,
  windDownQuery,
  type WindDownChoice,
  type WindDownItem,
  type WindDownOut,
} from "@/features/followups/api"

const CHOICE_LABEL: Record<WindDownChoice, string> = {
  keep: "Keep",
  pause: "Pause",
  withdraw: "Withdraw",
}

/**
 * "I've accepted an offer": one action pauses every automatic send at once, then lists what is still
 * in motion with keep / pause / withdraw. Withdrawing drafts an email for approval; nothing is sent
 * from here. Reopening brings everything back paused, never deleted.
 */
export function WindDownPage() {
  const qc = useQueryClient()
  const q = useQuery(windDownQuery())
  const [reason, setReason] = useState("")
  const set = (data: WindDownOut) =>
    qc.setQueryData(followupKeys.windDown, data)
  const start = useMutation({
    mutationFn: () => startWindDown(reason || null),
    onSuccess: set,
  })
  const reopen = useMutation({ mutationFn: reopenWindDown, onSuccess: set })

  if (q.isPending) return <p className="text-muted-foreground">Loading...</p>
  if (q.isError) return <p role="alert">{q.error.message}</p>
  const wd = q.data

  if (wd.status !== "active")
    return (
      <View>
        <PageHeader
          title="Wind down"
          description="Accepted an offer? This pauses every automatic send at once, then lets you decide what happens to everything else."
        />
        <p className="mb-3 max-w-prose text-sm text-muted-foreground">
          Once you start: {lowerFirst(WIND_DOWN_SENDING)}
        </p>
        {wd.status === "reopened" && (
          <p className="mb-3 text-sm" role="status">
            Your search was reopened: everything came back paused. Resume
            Autopilot when you are ready.
          </p>
        )}
        <form
          className="flex flex-wrap items-end gap-2 panel p-3"
          onSubmit={(e) => {
            e.preventDefault()
            start.mutate()
          }}
        >
          <label className="grid min-w-48 flex-1 gap-1 text-sm">
            Note (optional)
            <Input
              aria-label="Reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <Button type="submit" disabled={start.isPending}>
            I've accepted an offer
          </Button>
        </form>
        {start.isError && <p role="alert">{start.error.message}</p>}
      </View>
    )

  return (
    <View>
      <PageHeader
        title="Winding down"
        description={wd.reason ?? undefined}
        meta={
          <Chip tone={wd.autopilot_paused ? "warn" : "good"}>
            {wd.autopilot_paused
              ? "Automatic sending paused"
              : "Autopilot running"}
          </Chip>
        }
        actions={
          <div className="flex gap-2">
            <Button asChild variant="outline" size="sm">
              <a href={WIND_DOWN_SUMMARY_URL} download>
                Download summary
              </a>
            </Button>
            <Button size="sm" variant="outline" onClick={() => reopen.mutate()}>
              Reopen my search
            </Button>
          </div>
        }
      />
      <p
        role="note"
        aria-label="What still sends"
        className="mb-4 max-w-prose rounded-md border border-border bg-warn-soft px-3 py-2 text-sm text-foreground"
      >
        {wd.autopilot_paused
          ? WIND_DOWN_SENDING
          : "Autopilot was resumed during this wind-down. Messages you approve still send."}
      </p>
      <div className="grid gap-5">
        <Section title="Queued sends" items={wd.queued_sends} onSet={set} />
        <Section
          title="Approved, not sent"
          items={wd.approved_unsent}
          onSet={set}
        />
        {Object.entries(wd.live_applications).map(([stage, items]) => (
          <Section
            key={stage}
            title={`Live applications: ${stage}`}
            items={items}
            onSet={set}
          />
        ))}
        <Section title="Interviews ahead" items={wd.interviews} onSet={set} />
        <Section
          title="Pending actions"
          items={wd.pending_actions}
          onSet={set}
        />
        <Section
          title="Campaigns and schedules"
          items={wd.campaigns}
          onSet={set}
        />
      </div>
    </View>
  )
}

const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

function Section({
  title,
  items,
  onSet,
}: {
  title: string
  items: WindDownItem[]
  onSet: (d: WindDownOut) => void
}) {
  const choose = useMutation({
    mutationFn: ({ key, choice }: { key: string; choice: WindDownChoice }) =>
      chooseWindDown(key, choice),
    onSuccess: onSet,
  })
  return (
    <section aria-label={title} className="grid gap-2">
      <SectionHeader title={title} as="h3" />
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">None.</p>
      ) : (
        <ul className="panel p-0">
          {items.map((i) => (
            <li
              key={i.key}
              aria-label={i.label}
              className="flex flex-wrap items-center gap-2 border-t border-border px-3 row-pad first:border-t-0"
            >
              <div className="min-w-0 flex-1">
                <b className="font-semibold break-words">{i.label}</b>
                <p className="text-sm text-muted-foreground">{i.detail}</p>
                {i.effect && (
                  <p className="text-sm" role="status">
                    {CHOICE_LABEL[i.choice ?? "keep"]}: {i.effect}
                  </p>
                )}
              </div>
              {i.choices.length > 1 &&
                i.choices.map((c) => (
                  <Button
                    key={c}
                    size="sm"
                    variant={i.choice === c ? "default" : "outline"}
                    aria-pressed={i.choice === c}
                    disabled={choose.isPending}
                    onClick={() => choose.mutate({ key: i.key, choice: c })}
                  >
                    {CHOICE_LABEL[c]}
                  </Button>
                ))}
            </li>
          ))}
        </ul>
      )}
      {choose.isError && (
        <p role="alert" className="text-sm text-danger">
          {choose.error.message}
        </p>
      )}
    </section>
  )
}
