import { useQuery } from "@tanstack/react-query"
import { Chip, type ChipTone } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { healthQuery, type HealthComponent } from "../data/api"
import { SettingsBlock } from "../data/settings-block"

type Status = HealthComponent["status"]

/** Status in words. `unknown` is its own state: never shown as working. */
export const STATUS: Record<Status, { tone: ChipTone; label: string }> = {
  ok: { tone: "good", label: "OK" },
  warn: { tone: "warn", label: "Needs a look" },
  down: { tone: "danger", label: "Down" },
  unknown: { tone: "neutral", label: "Unknown" },
}
/** Any status the server adds later reads as unknown, not as OK. */
const statusOf = (s: string) => STATUS[s as Status] ?? STATUS.unknown

const NAMES: Record<string, string> = {
  database: "Database",
  worker: "Worker",
  sweep: "Last sweep",
  backup: "Last backup",
  disk: "Disk space",
  connections: "Connections",
}

const age = (seconds: number | null) => {
  if (seconds === null) return null
  const mins = Math.round(seconds / 60)
  if (mins < 1) return "under a minute"
  if (mins < 60) return `${mins} min`
  if (mins < 1440) return `${Math.round(mins / 60)} h`
  return `${Math.round(mins / 1440)} d`
}

/** Database, worker, sweep, backup, disk and connections, with the queue, from `/api/health/detail`. */
export function HealthPanel() {
  const q = useQuery(healthQuery())
  const h = q.data
  return (
    <div className="grid gap-4">
      <PageHeader
        title="System health"
        description="Whether the parts that work in the background are running. One alert is sent per lasting failure, and one when it recovers."
      />
      {q.isPending && <Skeleton className="h-40 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-danger">
          The health check could not be loaded, so every part is unknown.
        </p>
      )}
      {h && (
        <>
          <ul
            aria-label="Health checks"
            className="divide-y divide-border panel"
          >
            {h.components.map((c) => {
              const base = statusOf(c.status)
              // A backup or sweep that has not happened yet is "none yet" (the detail says how old the
              // instance is), not an unknown state.
              const noneYet =
                c.status === "unknown" && c.detail?.startsWith("None yet")
              const st = noneYet ? { ...base, label: "None yet" } : base
              return (
                <li
                  key={c.name}
                  aria-label={NAMES[c.name] ?? c.name}
                  className="flex flex-wrap items-center gap-3 p-3"
                >
                  <span className="w-32 font-semibold">
                    {NAMES[c.name] ?? c.name}
                  </span>
                  <Chip tone={st.tone}>{st.label}</Chip>
                  <span className="min-w-0 flex-1 text-muted-foreground">
                    {c.detail ??
                      (c.status === "unknown" ? "Not checked yet." : "")}
                  </span>
                </li>
              )
            })}
          </ul>
          <section aria-labelledby="queue-h" className="grid gap-2 panel p-4">
            <h3 id="queue-h" className="text-md">
              Queue and workers
            </h3>
            <p className="num" data-testid="queue">
              {h.queue.waiting} waiting, {h.queue.running} running,{" "}
              {h.queue.failed} failed
            </p>
            {h.workers.length === 0 ? (
              <p className="text-muted-foreground">
                No worker heartbeat seen. Nothing is swept or sent until a
                worker runs.
              </p>
            ) : (
              <ul aria-label="Workers" className="grid gap-1">
                {h.workers.map((w, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2">
                    <Chip tone={w.ok ? "good" : "danger"}>
                      {w.ok ? "Beating" : "Stale"}
                    </Chip>
                    <span className="text-muted-foreground">
                      {w.age_seconds === null
                        ? "No heartbeat yet"
                        : `Last heartbeat ${age(w.age_seconds)} ago`}
                      {w.workers > 1 ? `, ${w.workers} workers` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {h.connections.length > 0 && (
            <section aria-labelledby="conns-h" className="grid gap-2 panel p-4">
              <h3 id="conns-h" className="text-md">
                Each connection
              </h3>
              <ul aria-label="Connection health" className="grid gap-1">
                {h.connections.map((c) => {
                  const st =
                    c.health === "failing" ? STATUS.down : statusOf(c.health)
                  return (
                    <li
                      key={c.id}
                      className="flex flex-wrap items-center gap-2"
                    >
                      <span className="font-medium">{c.label}</span>
                      <Chip tone={c.enabled ? st.tone : "line"}>
                        {c.enabled ? st.label : "Paused"}
                      </Chip>
                      <span className="text-sm text-muted-foreground">
                        {c.last_checked_at
                          ? `Checked ${new Date(c.last_checked_at).toLocaleString()}`
                          : "Never checked"}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </section>
          )}
        </>
      )}
      <section aria-labelledby="thresholds-h" className="grid gap-2 panel p-4">
        <h3 id="thresholds-h" className="text-md">
          When to warn
        </h3>
        <SettingsBlock
          label="Health thresholds"
          keys={[
            "health.sweep_stale_hours",
            "health.backup_stale_hours",
            "health.disk_min_free_mb",
          ]}
        />
      </section>
    </div>
  )
}
