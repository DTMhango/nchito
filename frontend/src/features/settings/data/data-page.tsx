import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/page-header"
import { Chip } from "@/components/chip"
import { isApiError } from "@/lib/api/client"
import { backupsQuery, dataKeys, runBackup, runRetention } from "./api"
import { ExportSection } from "./export-section"
import { ImportFlow } from "./import-flow"
import { SettingsBlock } from "./settings-block"

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  })
/** The server answers 503 when it cannot run pg_dump. */
export const NO_PG_DUMP =
  "Backups need the PostgreSQL tool pg_dump on the server. Install the PostgreSQL client tools there (or set PG_BIN_DIR), then try again."

const mb = (n: number) => `${(n / 1_048_576).toFixed(1)} MB`

export function DataPage() {
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Data"
        description="Take your data out, bring data in, and keep it safe."
      />
      <ExportSection />
      <section aria-labelledby="import-h" className="grid gap-3 panel p-4">
        <div>
          <h3 id="import-h" className="text-md">
            Import
          </h3>
          <p className="text-muted-foreground">
            You always see what would be added, replaced or in conflict before
            anything is saved.
          </p>
        </div>
        <ImportFlow />
        <SettingsBlock
          label="Import and export limits"
          keys={[
            "data.old_kit_ai_extraction",
            "data.import_max_zip_mb",
            "data.import_max_file_mb",
            "data.import_max_files",
            "data.import_staging_hours",
            "data.export_link_minutes",
          ]}
        />
      </section>
      <BackupsSection />
      <RetentionSection />
    </div>
  )
}

function BackupsSection() {
  const qc = useQueryClient()
  const q = useQuery(backupsQuery())
  const run = useMutation({
    mutationFn: runBackup,
    onSuccess: () => {
      toast.success("Backup written")
      void qc.invalidateQueries({ queryKey: dataKeys.backups })
    },
  })
  const items = [...(q.data ?? [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at)
  )
  const last = items[0]
  return (
    <section aria-labelledby="backups-h" className="grid gap-4 panel p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1">
          <h3 id="backups-h" className="text-md">
            Backups
          </h3>
          <p className="text-muted-foreground" data-testid="last-backup">
            {q.isPending
              ? "Checking"
              : last
                ? `Last backup: ${when(last.created_at)}, ${mb(last.size_bytes)}, ${last.target}`
                : "No backup yet. Run one now."}
          </p>
        </div>
        <Button onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Backing up" : "Back up now"}
        </Button>
      </div>
      {run.isError && (
        <p role="alert" className="text-sm text-danger">
          {isApiError(run.error, 503) ? NO_PG_DUMP : run.error.message}
        </p>
      )}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          {q.error.message}
        </p>
      )}
      <SettingsBlock
        label="Backup schedule"
        keys={[
          "backups.cron",
          "backups.keep",
          "backups.target",
          "health.backup_stale_hours",
        ]}
      />
      {items.length > 0 && (
        <ul aria-label="Backups kept" className="divide-y divide-border">
          {items.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <span className="num">{when(b.created_at)}</span>
              <span className="text-muted-foreground">{mb(b.size_bytes)}</span>
              <Chip tone="line">{b.target}</Chip>
              {b.encrypted && <Chip tone="good">Encrypted</Chip>}
            </li>
          ))}
        </ul>
      )}
      <details className="rounded-md border border-border bg-surface p-3">
        <summary className="cursor-pointer font-semibold">
          How to restore
        </summary>
        <ol className="mt-2 grid list-decimal gap-1 pl-5">
          <li>
            Restoring happens outside the app, on the server, so it cannot be
            done by accident.
          </li>
          <li>Stop the app and the worker.</li>
          <li>
            Follow the restore steps in <code>docs/RUNBOOK.md</code> with the
            backup file you want. Keep your encryption key: without it the saved
            connections cannot be read.
          </li>
          <li>
            Start the app again. Automation stays paused until you resume it
            after a restore.
          </li>
        </ol>
      </details>
    </section>
  )
}

function RetentionSection() {
  const run = useMutation({
    mutationFn: runRetention,
    onSuccess: () => toast.success("Clean-up done"),
    onError: (e) => toast.error(e.message),
  })
  return (
    <section aria-labelledby="retention-h" className="grid gap-3 panel p-4">
      <div>
        <h3 id="retention-h" className="text-md">
          Retention
        </h3>
        <p className="text-muted-foreground">
          How long roles keep their full text, and when old notifications and
          temporary files are removed. What you have applied to is kept until
          you delete it, and the record that stops you applying twice is never
          removed.
        </p>
      </div>
      <SettingsBlock
        label="Retention settings"
        keys={[
          "retention.cron",
          "retention.below_threshold_text_days",
          "retention.unsubmitted_archive_days",
          "retention.notifications_days",
          "retention.temp_files_days",
        ]}
      />
      <div>
        <Button
          variant="outline"
          onClick={() => run.mutate()}
          disabled={run.isPending}
        >
          Run clean-up now
        </Button>
      </div>
    </section>
  )
}
