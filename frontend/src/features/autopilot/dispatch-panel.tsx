import { useState, type FormEvent } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { SectionHeader } from "@/components/page-header"
import {
  apKeys,
  cancelDispatch,
  dispatchAppsQuery,
  dispatchesQuery,
  markSent,
  type ApplicationSummary,
  type DispatchOut,
} from "./api"
import { CHANNEL_LABEL, canCancel, dispatchView, shortHash } from "./logic"

const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })

/** Attempts per application with what each one means (DESIGN 8.5, 18.3). */
export function DispatchPanel() {
  const apps = useQuery(dispatchAppsQuery())
  return (
    <section aria-label="Dispatch and reconciliation" className="grid gap-3">
      <SectionHeader
        title="Sending and reconciliation"
        aside="Every attempt is written down before anything is sent."
      />
      <p className="max-w-prose text-sm text-muted-foreground">
        If we cannot tell whether something left, it is marked uncertain, stays
        locked so the employer is not contacted twice, and is never sent again
        automatically. You settle it by checking and recording the outcome.
      </p>
      {apps.data && apps.data.length === 0 && (
        <EmptyState
          title="Nothing is being sent"
          description="Attempts appear here once an application is approved."
        />
      )}
      <ul className="grid gap-2.5">
        {apps.data?.map((a) => (
          <AppAttempts key={a.id} app={a} />
        ))}
      </ul>
    </section>
  )
}

function AppAttempts({ app }: { app: ApplicationSummary }) {
  const attempts = useQuery(dispatchesQuery(app.id))
  const qc = useQueryClient()
  const list = attempts.data ?? []
  if (attempts.isSuccess && list.length === 0) return null
  return (
    <li
      aria-label={`${app.title}, ${app.employer}`}
      className="grid gap-2 rounded-lg border border-border bg-surface p-3.5"
    >
      <div className="flex flex-wrap items-baseline gap-x-2">
        <Link
          to="/jobs/$id"
          params={{ id: app.job_id }}
          className="text-md font-semibold hover:underline"
        >
          {app.title}
        </Link>
        <span className="text-muted-foreground">{app.employer}</span>
      </div>
      <ul className="grid gap-2">
        {list.map((d) => (
          <Attempt key={d.id} app={app} d={d} qc={qc} />
        ))}
      </ul>
    </li>
  )
}

function Attempt({
  app,
  d,
  qc,
}: {
  app: ApplicationSummary
  d: DispatchOut
  qc: QueryClient
}) {
  const v = dispatchView(d)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: apKeys.dispatches(app.id) })
    void qc.invalidateQueries({ queryKey: apKeys.dispatchApps })
  }
  const cancel = useMutation({
    mutationFn: () => cancelDispatch(app.id, d.id),
    onSuccess: () => {
      toast.success("Cancelled. Nothing was sent.")
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <li className="grid gap-1.5 rounded-md bg-sunken p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={v.tone}>{v.label}</Chip>
        <span className="text-sm font-medium">{CHANNEL_LABEL[d.channel]}</span>
        <span className="num text-xs text-faint">
          packet {shortHash(d.packet_hash)} · {stamp(d.created_at)}
        </span>
        {canCancel(v) && (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            Cancel send
          </Button>
        )}
      </div>
      <p className="text-sm text-muted-foreground">{v.explain}</p>
      {v.evidence && (
        <p className="text-sm">
          <span className="text-faint">Proof: </span>
          <span className="num">{v.evidence}</span>
        </p>
      )}
      {v.kind === "uncertain" && <Reconcile app={app} onDone={refresh} />}
    </li>
  )
}

/**
 * The only ways forward from an uncertain attempt. There is deliberately no retry: sending
 * again could contact the employer twice. The owner checks, then records what happened.
 */
function Reconcile({
  app,
  onDone,
}: {
  app: ApplicationSummary
  onDone: () => void
}) {
  const [open, setOpen] = useState(false)
  const [reference, setReference] = useState("")
  const qc = useQueryClient()
  const record = useMutation({
    mutationFn: () =>
      markSent(
        app.id,
        reference.trim() || null,
        "Reconciled by the owner after an uncertain send."
      ),
    onSuccess: () => {
      toast.success(`Recorded: ${app.employer} received it.`)
      void qc.invalidateQueries({ queryKey: ["applications"] })
      setOpen(false)
      onDone()
    },
    onError: (e) => toast.error(e.message),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    record.mutate()
  }
  return (
    <div className="grid gap-2 border-t border-border pt-2">
      <p className="text-sm">
        <b className="font-semibold">To reconcile:</b> check your sent mail or
        the employer's portal. The mailbox is also watched for a confirmation.
      </p>
      {open ? (
        <form
          onSubmit={submit}
          aria-label="Record that it arrived"
          className="flex flex-wrap items-end gap-2"
        >
          <label className="grid gap-1 text-sm font-medium">
            Reference or what you saw (optional)
            <Input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Confirmation number or email subject"
              className="w-72 max-w-full"
            />
          </label>
          <Button type="submit" disabled={record.isPending}>
            Record that it arrived
          </Button>
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
            Not yet
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setOpen(true)}>
            I checked: it arrived
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link to="/jobs/$id" params={{ id: app.job_id }}>
              Open the role
            </Link>
          </Button>
        </div>
      )}
    </div>
  )
}
