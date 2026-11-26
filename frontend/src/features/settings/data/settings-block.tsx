import { useQuery } from "@tanstack/react-query"
import { Skeleton } from "@/components/ui/skeleton"
import { settingsQuery } from "../api"
import { SettingRow } from "../setting-row"

/** Registry settings picked by key, rendered from their metadata (no bespoke code per setting). */
export function SettingsBlock({
  keys,
  label,
}: {
  keys: string[]
  label: string
}) {
  const q = useQuery(settingsQuery())
  if (q.isPending) return <Skeleton className="h-24 w-full bg-sunken" />
  const rows = (q.data ?? [])
    .flatMap((g) => g.settings)
    .filter((s) => keys.includes(s.key))
    .sort((a, b) => keys.indexOf(a.key) - keys.indexOf(b.key))
  if (rows.length === 0) return null
  return (
    <ul aria-label={label}>
      {rows.map((s) => (
        <SettingRow key={s.key} setting={s} />
      ))}
    </ul>
  )
}
