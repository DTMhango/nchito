import { useMemo, useState } from "react"
import { useInfiniteQuery, useQueries } from "@tanstack/react-query"
import {
  groupJobsQuery,
  jobCountQuery,
  jobsInfiniteQuery,
  type ListParams,
} from "./api"
import {
  conditionSet,
  filterConditions,
  TABS,
  tabConditions,
  type MatchesSearch,
  type TabId,
} from "./filters"
import { pickDrill } from "@/features/insights/drill-search"
import type { ListJob } from "./format"
import type { Condition } from "./types"

export type ListRow =
  | { kind: "group"; key: string; value: string; count: number; open: boolean }
  | { kind: "job"; key: string; job: ListJob }
  | { kind: "status"; key: string; text: string }

/** List params for a tab plus the current filter. */
export function listParams(
  search: MatchesSearch,
  tab: TabId = search.tab,
  extra: Condition[] = []
): ListParams {
  return {
    conditions: conditionSet([
      ...tabConditions(tab),
      ...filterConditions(search),
      ...extra,
    ]),
    q: search.q?.trim() || undefined,
    sort: search.sort,
    drill: pickDrill(search),
  }
}

/** Live counts per inbox tab, with the current filter applied. */
export function useTabCounts(search: MatchesSearch) {
  const results = useQueries({
    queries: TABS.map((t) => jobCountQuery(listParams(search, t.id))),
  })
  return Object.fromEntries(
    TABS.map((t, i) => [t.id, results[i].data ?? null])
  ) as Record<TabId, number | null>
}

const COLLAPSE_AFTER = 6

/**
 * The rows the list shows: jobs, or group headers with their jobs when grouped. Grouped lists
 * fetch each open group on its own, so a job in a multi-valued facet appears in each group.
 */
export function useJobList(search: MatchesSearch) {
  const base = listParams(search)
  const grouped = !!search.g
  const main = useInfiniteQuery({
    ...jobsInfiniteQuery({ ...base, group_by: search.g }),
  })
  const groups = useMemo(
    () => (grouped ? (main.data?.pages[0]?.groups ?? []) : []),
    [grouped, main.data]
  )

  // Collapsed state per grouping; groups past the first few start closed.
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const groupKey = (v: string) => `${search.g}::${v}`
  const isOpen = (v: string, i: number) =>
    toggled[groupKey(v)] ?? i < COLLAPSE_AFTER
  const toggleGroup = (v: string) => {
    const i = groups.findIndex((g) => g.value === v)
    setToggled((t) => ({ ...t, [groupKey(v)]: !isOpen(v, i) }))
  }

  const openGroups = groups.filter((g, i) => isOpen(g.value, i))
  const groupResults = useQueries({
    queries: openGroups.map((g) =>
      groupJobsQuery(
        listParams(search, search.tab, [
          {
            type: "values",
            facet: search.g as string,
            include: [g.value],
            exclude: [],
            match: "any",
          },
        ])
      )
    ),
  })

  const rows: ListRow[] = []
  if (grouped) {
    groups.forEach((g, i) => {
      const open = isOpen(g.value, i)
      rows.push({
        kind: "group",
        key: `g:${g.value}`,
        value: g.value,
        count: g.count,
        open,
      })
      if (!open) return
      const r = groupResults[openGroups.findIndex((o) => o.value === g.value)]
      if (!r?.data) {
        rows.push({ kind: "status", key: `s:${g.value}`, text: "Loading…" })
        return
      }
      for (const job of r.data.items as ListJob[])
        rows.push({ kind: "job", key: `${g.value}:${job.id}`, job })
      const more = (r.data.total ?? 0) - r.data.items.length
      if (more > 0)
        rows.push({
          kind: "status",
          key: `m:${g.value}`,
          text: `${more} more in this group. Narrow the filter to see them.`,
        })
    })
  } else {
    for (const page of main.data?.pages ?? [])
      for (const job of page.items as ListJob[])
        rows.push({ kind: "job", key: job.id, job })
  }

  return {
    rows,
    total: main.data?.pages[0]?.total ?? null,
    isLoading: main.isLoading,
    isError: main.isError,
    error: main.error,
    hasNextPage: !grouped && main.hasNextPage,
    fetchNextPage: main.fetchNextPage,
    isFetchingNextPage: main.isFetchingNextPage,
    toggleGroup,
  }
}
