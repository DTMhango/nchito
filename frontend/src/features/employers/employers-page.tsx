import { useDeferredValue, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { DataTable, type Column } from "@/components/data-table"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Input } from "@/components/ui/input"
import { View } from "@/components/view"
import {
  employersQuery,
  STATE_LABEL,
  type EmployerRow,
  type EmployerState,
} from "./api"
import { EmployerChip } from "./employer-chip"

const ALL = "all"
const STATES = Object.keys(STATE_LABEL) as EmployerState[]

export const shortDate = (iso: string | null | undefined) =>
  iso
    ? new Intl.DateTimeFormat("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
      }).format(new Date(iso))
    : "Never"

/** Employers: every employer you have seen or applied to, and what that means for the next role. */
export function EmployersPage() {
  const [state, setState] = useState<string>(ALL)
  const [text, setText] = useState("")
  const q = useDeferredValue(text)
  const list = useQuery(employersQuery(state === ALL ? "" : state, q))
  const rows = list.data ?? []

  const columns: Column<EmployerRow>[] = [
    {
      id: "name",
      header: "Employer",
      sortValue: (r) => r.name,
      cell: (r) => (
        <Link
          to="/employers/$key"
          params={{ key: r.key }}
          className="font-semibold hover:underline"
        >
          {r.name}
        </Link>
      ),
    },
    {
      id: "state",
      header: "State",
      sortValue: (r) => r.state,
      cell: (r) => (
        <EmployerChip chip={{ state: r.state, text: r.state_text }} hide={[]} />
      ),
    },
    {
      id: "apps",
      header: "Applications",
      sortValue: (r) => r.applications,
      hideBelow: "sm",
      cell: (r) => <span className="num">{r.applications}</span>,
    },
    {
      id: "last",
      header: "Last applied",
      sortValue: (r) => r.last_applied_at ?? "",
      hideBelow: "md",
      cell: (r) => (
        <span className="text-muted-foreground">
          {shortDate(r.last_applied_at)}
        </span>
      ),
    },
    {
      id: "roles",
      header: "Roles seen",
      sortValue: (r) => r.roles_seen,
      hideBelow: "lg",
      cell: (r) => (
        <span className="num">
          {r.roles_seen}
          {r.held_roles > 0 ? ` (${r.held_roles} held)` : ""}
        </span>
      ),
    },
  ]

  return (
    <View>
      <PageHeader
        title="Employers"
        description="One role per employer at a time, with a cooldown after each application. Set a different rule for an employer, or never apply to it."
      />
      <div
        role="search"
        aria-label="Filter employers"
        className="mb-4 flex flex-wrap items-center gap-2"
      >
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <Input
            aria-label="Search employers"
            placeholder="Search employers"
            className="pl-8"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <select
          aria-label="State"
          className="h-8 rounded-md border border-border bg-surface px-2 text-sm"
          value={state}
          onChange={(e) => setState(e.target.value)}
        >
          <option value={ALL}>All states</option>
          {STATES.map((s) => (
            <option key={s} value={s}>
              {STATE_LABEL[s]}
            </option>
          ))}
        </select>
      </div>
      {list.isError ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>Couldn't load employers</AlertTitle>
          <AlertDescription>{list.error.message}</AlertDescription>
        </Alert>
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          getRowId={(r) => r.key}
          caption="Employers"
          empty={
            <EmptyState
              title={list.isPending ? "Loading employers" : "No employers"}
              description={
                list.isPending
                  ? undefined
                  : "Employers appear here as roles are found and applications are made."
              }
            />
          }
        />
      )}
    </View>
  )
}
