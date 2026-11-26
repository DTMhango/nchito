import { useQuery } from "@tanstack/react-query"
import { Chip, type ChipTone } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { api, unwrap } from "@/lib/api/client"
import { backupsQuery, healthQuery } from "../data/api"

const runsQuery = () => ({
  queryKey: ["health", "runs"] as const,
  queryFn: async () =>
    (await unwrap(api.GET("/api/runs", { params: { query: { limit: 100 } } })))
      .items,
  refetchInterval: 30_000,
})

const ago = (iso: string | null | undefined) => {
  if (!iso) return null
  const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60_000))
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins} min ago`
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`
  return `${Math.round(mins / 1440)} d ago`
}

type Row = { label: string; tone: ChipTone; status: string; detail: string }

/** Worker, last sweep, last backup and the queue, in plain words. */
export function HealthPanel() {
  const health = useQuery(healthQuery())
  const runs = useQuery(runsQuery())
  const backups = useQuery(backupsQuery())

  const loading = health.isPending || runs.isPending || backups.isPending
  const rows: Row[] = []
  if (health.data) {
    const w = health.data.worker
    rows.push({
      label: "Worker",
      tone: w.ok ? "good" : "danger",
      status: w.ok ? "Running" : "Not running",
      detail: w.last_beat_at
        ? `Last heartbeat ${ago(w.last_beat_at)}. Nothing is swept or sent while it is stopped.`
        : "No heartbeat seen. Nothing is swept or sent while it is stopped.",
    })
    rows.push({
      label: "Database",
      tone: health.data.db.ok ? "good" : "danger",
      status: health.data.db.ok ? "Reachable" : "Unreachable",
      detail: health.data.db.error ?? `Version ${health.data.version}`,
    })
  }
  if (runs.data) {
    const sweeps = runs.data
      .filter((r) => r.kind === "sweep" && !r.dry_run)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
    const done = sweeps.find(
      (r) => r.status === "succeeded" || r.status === "partial"
    )
    const failed = sweeps[0] && sweeps[0].status === "failed"
    rows.push({
      label: "Last sweep",
      tone: failed ? "danger" : done ? "good" : "neutral",
      status: failed ? "Failed" : done ? "OK" : "None yet",
      detail: done
        ? `Finished ${ago(done.finished_at ?? done.updated_at)}.`
        : "No finished sweep yet.",
    })
    const waiting = runs.data.filter((r) => r.status === "queued").length
    const active = runs.data.filter((r) => r.status === "running").length
    rows.push({
      label: "Queue",
      tone: "neutral",
      status: `${waiting} waiting`,
      detail: `${active} running now.`,
    })
  }
  if (backups.data) {
    const last = [...backups.data].sort((a, b) =>
      b.created_at.localeCompare(a.created_at)
    )[0]
    rows.push({
      label: "Last backup",
      tone: last ? "good" : "warn",
      status: last ? "Done" : "None yet",
      detail: last
        ? `${ago(last.created_at)}, kept on ${last.target}.`
        : "Nothing is backed up. Run one under Data.",
    })
  }

  return (
    <div className="grid gap-4">
      <PageHeader
        title="System health"
        description="Whether the parts that work in the background are running. One alert is sent per lasting failure, and one when it recovers."
      />
      {loading && <Skeleton className="h-40 w-full bg-sunken" />}
      {(health.isError || runs.isError || backups.isError) && (
        <p role="alert" className="text-danger">
          Some health checks could not be loaded.
        </p>
      )}
      <ul aria-label="Health checks" className="divide-y divide-border panel">
        {rows.map((r) => (
          <li key={r.label} className="flex flex-wrap items-center gap-3 p-3">
            <span className="w-32 font-semibold">{r.label}</span>
            <Chip tone={r.tone}>{r.status}</Chip>
            <span className="min-w-0 flex-1 text-muted-foreground">
              {r.detail}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
