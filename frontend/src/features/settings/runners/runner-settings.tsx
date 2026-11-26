import { useQuery } from "@tanstack/react-query"
import { SectionHeader } from "@/components/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { settingsQuery } from "@/features/settings/api"
import { SettingRow } from "@/features/settings/setting-row"

/** The registry group the gateway reads (`runners.*`): leases, claim and call rates, server caps. */
export const RUNNERS_GROUP = "runners"

/** Settings > Runners group: every `runners.*` setting, edited and audited through the settings API. */
export function RunnerSettings() {
  const q = useQuery(settingsQuery())
  const group = q.data?.find((g) => g.key === RUNNERS_GROUP)
  return (
    <section
      id="runner-settings"
      aria-labelledby="runner-settings-h"
      className="grid gap-3"
    >
      <SectionHeader
        as="h3"
        title={<span id="runner-settings-h">Runner settings</span>}
        aside="Limits for every runner: how long a task is held, how many tasks and calls, and the server runner's spend. Each change is recorded."
      />
      {q.isPending && <Skeleton className="h-24 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          Could not load runner settings. Reload to try again.
        </p>
      )}
      {q.isSuccess && !group && (
        <p className="text-sm text-muted-foreground">
          No runner settings are registered.
        </p>
      )}
      {group && (
        <ul aria-label="Runner settings" className="panel p-4">
          {group.settings.map((s) => (
            <SettingRow key={s.key} setting={s} />
          ))}
        </ul>
      )}
    </section>
  )
}
