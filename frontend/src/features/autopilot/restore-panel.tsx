import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { DatabaseBackup } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { keys } from "@/lib/api/endpoints"
import {
  apKeys,
  errorText,
  refusalOf,
  restoreQuery,
  resumeAfterRestore,
  type DispatchOut,
} from "./api"
import { CHANNEL_LABEL, shortHash, stamp } from "./logic"

/**
 * Paused for a restore (DESIGN 18.3): after a backup is restored, sending stays paused until
 * every send that may have left after the backup was taken is settled. The resume is refused
 * (409 `restore_unreconciled`) while any is outstanding, and the refusal lists them.
 */
export function RestorePanel() {
  const qc = useQueryClient()
  const q = useQuery(restoreQuery())
  const [outstanding, setOutstanding] = useState<string[] | null>(null)
  const resume = useMutation({
    mutationFn: resumeAfterRestore,
    onSuccess: () => {
      setOutstanding(null)
      toast.success("Resumed after the restore.")
      void qc.invalidateQueries({ queryKey: keys.autopilot })
    },
    onError: (e) => {
      const r = refusalOf(e)
      if (r?.code === "restore_unreconciled") setOutstanding(r.outstanding)
      else toast.error(errorText(e))
      void qc.invalidateQueries({ queryKey: apKeys.restore })
    },
  })
  const s = q.data
  if (!s?.active) return null
  const byId = new Map(s.outstanding.map((d) => [d.id, d]))
  return (
    <section
      aria-label="Paused for a restore"
      className="grid gap-3 rounded-lg border border-border bg-warn-soft p-4 text-warn"
    >
      <div className="flex flex-wrap items-center gap-3">
        <DatabaseBackup className="size-5 shrink-0" aria-hidden="true" />
        <div className="grid min-w-0 flex-1 gap-1">
          <h3 className="text-md">Paused after a restore</h3>
          <p className="text-sm">
            A backup was restored
            {s.entered_at && ` on ${stamp(s.entered_at)}`}
            {s.backup_taken_at &&
              `. The backup was taken ${stamp(s.backup_taken_at)}`}
            . Anything sent after that may not be on record, so sending stays
            paused until each uncertain send is settled under Sending.
          </p>
        </div>
        <Button disabled={resume.isPending} onClick={() => resume.mutate()}>
          Resume after restore
        </Button>
      </div>
      <OutstandingList title="Still to settle" items={s.outstanding} />
      {s.held_application_ids.length > 0 && (
        <p className="text-sm">
          {s.held_application_ids.length} application
          {s.held_application_ids.length === 1 ? " is" : "s are"} held until
          then.
        </p>
      )}
      {outstanding && (
        <div role="alert" className="grid gap-1 text-sm">
          <b className="font-semibold">
            Not resumed: {outstanding.length} send
            {outstanding.length === 1 ? " is" : "s are"} still outstanding.
          </b>
          <ul className="grid gap-0.5">
            {outstanding.map((id) => {
              const d = byId.get(id)
              return (
                <li key={id}>
                  {d ? describe(d) : `Attempt ${id.slice(0, 8)}`}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}

const describe = (d: DispatchOut) =>
  `${CHANNEL_LABEL[d.channel]} attempt, packet ${shortHash(d.packet_hash)}, ${stamp(d.created_at)}`

function OutstandingList({
  title,
  items,
}: {
  title: string
  items: DispatchOut[]
}) {
  return (
    <div className="grid gap-1 text-sm">
      <h4 className="eyebrow text-warn">{title}</h4>
      {items.length === 0 ? (
        <p>Nothing. You can resume.</p>
      ) : (
        <ul className="grid gap-0.5">
          {items.map((d) => (
            <li key={d.id}>{describe(d)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
