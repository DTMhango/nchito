import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { Columns3, Link2, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { View } from "@/components/view"
import { cn } from "@/lib/utils"
import { searchJobsQuery } from "../api"
import {
  compareQuery,
  type CompareOut,
  joinIds,
  MAX_COMPARE,
  MIN_COMPARE,
  parseIds,
} from "./api"
import { BestMark, CellView, differs, groupRows } from "./rows"

/** Compare 2 to 4 roles side by side (DESIGN 18.4). The roles live in the link, so it can be shared. */
export function ComparePage({
  ids: raw,
  onIds,
}: {
  ids: string
  onIds: (ids: string) => void
}) {
  const ids = parseIds(raw)
  const q = useQuery(compareQuery(ids))
  const set = (next: string[]) => onIds(joinIds(next))

  return (
    <View>
      <PageHeader
        eyebrow="Matches"
        title="Compare roles"
        description="Differences are highlighted. A fact the posting does not state is shown as not stated, never as no."
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void navigator.clipboard
                ?.writeText(window.location.href)
                .then(() => toast.success("Link copied"))
                .catch(() => toast.error("Couldn't copy the link"))
            }}
          >
            <Link2 aria-hidden="true" />
            Copy link
          </Button>
        }
      />
      <Picker ids={ids} onAdd={(id) => set([...ids, id])} />

      {ids.length < MIN_COMPARE ? (
        <EmptyState
          icon={Columns3}
          title="Pick at least two roles"
          description={`Tick roles in Matches and choose Compare, or add them above. You can compare up to ${MAX_COMPARE}.`}
          actions={
            <Button asChild size="sm" variant="outline">
              <Link to="/matches">Go to Matches</Link>
            </Button>
          }
        />
      ) : q.isPending ? (
        <p className="text-muted-foreground">Loading the comparison...</p>
      ) : q.isError ? (
        <p role="alert" className="text-danger">
          Couldn't load the comparison. {q.error.message}
        </p>
      ) : (
        <Grid
          data={q.data}
          onRemove={(id) => set(ids.filter((x) => x !== id))}
        />
      )}
    </View>
  )
}

function Picker({
  ids,
  onAdd,
}: {
  ids: string[]
  onAdd: (id: string) => void
}) {
  const [text, setText] = useState("")
  const search = useQuery(searchJobsQuery(text))
  const full = ids.length >= MAX_COMPARE
  return (
    <div className="mb-5 grid max-w-[34rem] gap-1.5">
      <label htmlFor="compare-add" className="text-sm font-semibold">
        Add a role
      </label>
      <Input
        id="compare-add"
        value={text}
        disabled={full}
        placeholder={
          full ? `Up to ${MAX_COMPARE} roles` : "Search by title or employer"
        }
        onChange={(e) => setText(e.target.value)}
      />
      {text.trim() && !full && (
        <ul
          aria-label="Matching roles"
          className="m-0 grid list-none gap-0 panel p-1"
        >
          {(search.data ?? [])
            .filter((j) => !ids.includes(j.id))
            .slice(0, 6)
            .map((j) => (
              <li key={j.id}>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-auto w-full justify-start py-1.5 text-left whitespace-normal"
                  onClick={() => {
                    onAdd(j.id)
                    setText("")
                  }}
                >
                  <Plus aria-hidden="true" />
                  {j.title}, {j.employer}
                </Button>
              </li>
            ))}
          {search.isSuccess && search.data.length === 0 && (
            <li className="px-2 py-1.5 text-sm text-muted-foreground">
              No roles match.
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

function Grid({
  data,
  onRemove,
}: {
  data: CompareOut
  onRemove: (id: string) => void
}) {
  const { jobs } = data
  const winner = jobs.find((j) => j.id === data.winner_id)
  return (
    <div className="grid gap-3">
      {winner && (
        <p role="status" data-winner={winner.id} className="text-sm">
          <b>{winner.title}</b> is the employer group's chosen role
          {data.winner_reason ? `: ${data.winner_reason}` : "."}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] border-collapse text-sm">
          <caption className="sr-only">Roles side by side</caption>
          <thead>
            <tr>
              <th scope="col" className="w-44 p-2 text-left" />
              {jobs.map((j) => (
                <th
                  key={j.id}
                  scope="col"
                  className="min-w-44 border-b border-border p-2 text-left align-top"
                >
                  <span className="flex items-start gap-1">
                    <span className="grid min-w-0 flex-1">
                      <Link
                        to="/jobs/$id"
                        params={{ id: j.id }}
                        search={{ tab: "overview" }}
                        className="font-semibold text-primary-ink underline"
                      >
                        {j.title}
                      </Link>
                      <span className="font-normal text-muted-foreground">
                        {j.employer}
                        {j.location ? `, ${j.location}` : ""}
                      </span>
                      {j.campaign_name && (
                        <span className="text-xs font-normal text-faint">
                          Scored by {j.campaign_name}
                        </span>
                      )}
                    </span>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Remove ${j.title} from the comparison`}
                      onClick={() => onRemove(j.id)}
                    >
                      <X aria-hidden="true" />
                    </Button>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          {groupRows(data.rows).map((s) => (
            <tbody key={s.group} aria-label={s.title}>
              <tr>
                <th
                  colSpan={jobs.length + 1}
                  scope="colgroup"
                  className="pt-5 pb-1 text-left eyebrow"
                >
                  {s.title}
                </th>
              </tr>
              {s.rows.map((r) => {
                const diff = differs(r)
                return (
                  <tr
                    key={r.key}
                    data-row={r.key}
                    data-differs={diff || undefined}
                    data-comparable={r.comparable}
                    className={cn(
                      "border-t border-border",
                      diff && "bg-highlight-soft"
                    )}
                  >
                    <th
                      scope="row"
                      className="p-2 text-left align-top font-semibold"
                    >
                      {r.label}
                      {diff && <span className="sr-only"> (differs)</span>}
                      {r.note && (
                        <span
                          className="mt-0.5 block text-xs font-normal text-muted-foreground"
                          data-row-note
                        >
                          {r.comparable ? r.note : `Not comparable: ${r.note}`}
                        </span>
                      )}
                    </th>
                    {r.cells.map((c, i) => (
                      <td
                        key={jobs[i]?.id ?? i}
                        data-best={r.best_index === i || undefined}
                        className="p-2 align-top"
                      >
                        <CellView cell={c} pay={r.group === "pay"} />
                        {r.best_index === i && <BestMark />}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  )
}
