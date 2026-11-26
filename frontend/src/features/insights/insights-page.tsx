import { useQuery } from "@tanstack/react-query"
import { BarChart3 } from "lucide-react"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { View } from "@/components/view"
import { campaignsQuery, tracksQuery } from "@/features/campaigns/api"
import { insightsQuery, type InsightsFilters } from "./api"
import { activeFilterCount, type InsightsSearch } from "./lib"
import {
  AutomationSection,
  FunnelSection,
  RatesSection,
  SourcesSection,
  SpendSection,
  TimeSection,
} from "./sections"

const field =
  "h-8 min-w-0 rounded-md border border-border bg-surface px-2 text-sm text-foreground"

type Option = { value: string; label: string }

function Pick({
  label,
  value,
  options,
  onChange,
  any = "All",
}: {
  label: string
  value: string | undefined
  options: Option[]
  onChange: (v: string | undefined) => void
  any?: string
}) {
  const shown =
    value && !options.some((o) => o.value === value)
      ? [...options, { value, label: value }]
      : options
  return (
    <label className="grid gap-1 text-sm text-muted-foreground">
      {label}
      <select
        className={field}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        <option value="">{any}</option>
        {shown.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Insights: how the search is going (DESIGN 10.3). Every number comes from the database; no model calls. */
export function InsightsPage({
  search,
  onSearch,
}: {
  search: InsightsSearch
  onSearch: (next: InsightsSearch) => void
}) {
  const filters: InsightsFilters = { ...search }
  const q = useQuery(insightsQuery(filters))
  const campaigns = useQuery(campaignsQuery())
  const tracks = useQuery(tracksQuery())
  const set = (patch: Partial<InsightsSearch>) =>
    onSearch({ ...search, ...patch })
  const report = q.data
  const active = activeFilterCount(filters)

  const noData =
    !!report &&
    report.funnel.length === 0 &&
    report.sources.length === 0 &&
    report.spend.rows.length === 0

  return (
    <View>
      <PageHeader
        title="Insights"
        description="How the search is going, and where your time and money work best. Counts and rates come straight from your records; small samples are marked."
      />
      <form
        aria-label="Insights filters"
        className="mb-5 flex flex-wrap items-end gap-3"
        onSubmit={(e) => e.preventDefault()}
      >
        <label className="grid gap-1 text-sm text-muted-foreground">
          From
          <input
            type="date"
            className={field}
            value={search.since ?? report?.since ?? ""}
            onChange={(e) => set({ since: e.target.value || undefined })}
          />
        </label>
        <label className="grid gap-1 text-sm text-muted-foreground">
          To
          <input
            type="date"
            className={field}
            value={search.until ?? report?.until ?? ""}
            onChange={(e) => set({ until: e.target.value || undefined })}
          />
        </label>
        <Pick
          label="Campaign"
          value={search.campaign_id}
          options={(campaigns.data ?? []).map((c) => ({
            value: c.id,
            label: c.name,
          }))}
          onChange={(v) => set({ campaign_id: v })}
        />
        <Pick
          label="Track"
          value={search.track_id}
          options={(tracks.data ?? []).map((t) => ({
            value: t.id,
            label: t.name,
          }))}
          onChange={(v) => set({ track_id: v })}
        />
        <Pick
          label="Source"
          value={search.source_id}
          options={(report?.response.by_source ?? [])
            .filter((r) => r.key !== "none")
            .map((r) => ({ value: r.key, label: r.label }))}
          onChange={(v) => set({ source_id: v })}
        />
        <Pick
          label="Market"
          value={search.country}
          options={(report?.response.by_market ?? [])
            .filter((r) => r.key !== "Not stated")
            .map((r) => ({ value: r.key, label: r.label }))}
          onChange={(v) => set({ country: v })}
        />
        <Pick
          label="Channel"
          value={search.channel}
          options={[
            { value: "email", label: "Email" },
            { value: "browser", label: "Browser" },
            { value: "manual", label: "Manual" },
          ]}
          onChange={(v) => set({ channel: v as InsightsSearch["channel"] })}
        />
        <Pick
          label="Spend by"
          value={search.period ?? "week"}
          any="Week"
          options={[{ value: "month", label: "Month" }]}
          onChange={(v) => set({ period: v as InsightsSearch["period"] })}
        />
        {active > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onSearch({ period: search.period })}
          >
            Clear filters ({active})
          </Button>
        )}
      </form>

      {q.isPending && (
        <p role="status" className="text-sm text-muted-foreground">
          Loading insights...
        </p>
      )}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          Insights could not be loaded. Try again in a moment.
        </p>
      )}
      {report && (
        <>
          <p className="mb-4 text-sm text-muted-foreground">
            {report.since} to {report.until}.{" "}
            {report.notes.map((n) => (
              <span key={n}>{n} </span>
            ))}
          </p>
          {noData ? (
            <EmptyState
              icon={BarChart3}
              title="There isn't enough data yet"
              description="Insights fill in once roles have been found, applications sent and replies come back. Widen the dates or clear a filter if you expected to see something here."
            />
          ) : (
            <div className="grid gap-9">
              <FunnelSection funnel={report.funnel} filters={filters} />
              <RatesSection report={report} filters={filters} />
              <TimeSection report={report} />
              <SpendSection report={report} />
              <SourcesSection sources={report.sources} filters={filters} />
              <AutomationSection report={report} />
            </div>
          )}
        </>
      )}
    </View>
  )
}
