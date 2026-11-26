import { useQuery } from "@tanstack/react-query"
import { EmptyState } from "@/components/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { settingsQuery } from "@/features/settings/api"
import { SettingRow } from "@/features/settings/setting-row"
import { SOURCES_GROUP } from "./connectors"

/**
 * The `sources` settings group (JobSpy, careers pages, web search), edited from registry
 * metadata alone. A source may override any of these for itself in its own settings.
 */
export function DiscoverySettings() {
  const q = useQuery(settingsQuery())
  if (q.isPending) return <Skeleton className="h-40 w-full" />
  if (q.isError)
    return (
      <EmptyState
        title="Could not load the discovery settings"
        description={q.error.message}
      />
    )
  const group = q.data.find((g) => g.key === SOURCES_GROUP)
  if (!group)
    return (
      <EmptyState
        title="No discovery settings"
        description="This server has no settings for JobSpy, careers pages or web search."
      />
    )
  return (
    <section aria-label={group.label} className="panel p-4">
      <p className="mb-2 text-sm text-muted-foreground">
        These apply to every JobSpy, careers page and web search source. A
        source can change any of them for itself in its own settings.
      </p>
      <ul>
        {group.settings.map((s) => (
          <SettingRow key={s.key} setting={s} />
        ))}
      </ul>
    </section>
  )
}
