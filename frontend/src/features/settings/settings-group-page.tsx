import { useQuery } from "@tanstack/react-query"
import { PageHeader } from "@/components/page-header"
import { EmptyState } from "@/components/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { settingsQuery } from "./api"
import { SettingRow } from "./setting-row"

/** Which registry groups each settings screen shows (DESIGN 16). The registry owns the rest. */
export const SETTINGS_PAGES = {
  general: {
    title: "General",
    lead: "The app name, your time zone and the currency amounts are shown in.",
    groups: ["general"],
  },
  schedule: {
    title: "Schedule",
    lead: "When sweeps run, what happens after a missed run, and how much they overlap.",
    groups: ["schedule"],
  },
  scoring: {
    title: "Scoring",
    lead: "Thresholds, how unknown pay or eligibility is treated, and the one-role-per-employer rules.",
    groups: ["scoring", "matching"],
  },
  automation: {
    title: "Automation",
    lead: "Mode, caps, quiet hours, cooldowns and what to do with questions it has not seen.",
    groups: ["automation", "answers"],
  },
  documents: {
    title: "Documents",
    lead: "Length limits and the default template for CVs and letters.",
    groups: ["documents"],
  },
  retention: {
    title: "Retention",
    lead: "How long roles keep their full text before only a minimal record is left.",
    groups: ["retention"],
  },
  reconcile: {
    title: "Reconcile",
    lead: "How long to wait for a confirmation before asking you.",
    groups: ["reconcile"],
  },
  notifications: {
    title: "Notifications",
    lead: "What reaches you and where. Nothing goes out until a channel is connected.",
    groups: ["notifications"],
  },
} as const

export type SettingsPageKey = keyof typeof SETTINGS_PAGES

/** Every setting in the chosen groups, editable from registry metadata alone. */
export function SettingsGroupPage({ page }: { page: SettingsPageKey }) {
  const def = SETTINGS_PAGES[page]
  const q = useQuery(settingsQuery())
  const groups = (q.data ?? []).filter((g) =>
    (def.groups as readonly string[]).includes(g.key)
  )
  return (
    <div>
      <PageHeader title={def.title} description={def.lead} />
      {q.isPending && <Skeleton className="h-40 w-full bg-sunken" />}
      {q.isError && (
        <EmptyState
          title="Could not load settings"
          description="Check the connection and reload."
        />
      )}
      {q.isSuccess && groups.length === 0 && (
        <EmptyState
          title="Nothing to set here yet"
          description="No settings are registered for this section."
        />
      )}
      <div className="grid gap-6">
        {groups.map((g) => (
          <section key={g.key} aria-label={g.label} className="panel p-4">
            {groups.length > 1 && <h3 className="mb-1 text-md">{g.label}</h3>}
            <ul>
              {g.settings.map((s) => (
                <SettingRow key={s.key} setting={s} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
