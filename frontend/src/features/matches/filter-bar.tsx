import { useEffect, useRef, useState, type ReactNode, type Ref } from "react"
import { Search, SlidersHorizontal, X } from "lucide-react"
import { KeyHint } from "@/components/key-hint"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { cn } from "@/lib/utils"
import { FacetButton, FacetPanel, type FacetSels } from "./facet-controls"
import {
  activeCount,
  DEFAULT_SORT,
  SORTS,
  summarise,
  type MatchesSearch,
} from "./filters"
import type { FacetCatalogEntry } from "./types"

type Patch = Partial<MatchesSearch>

type FilterBarProps = {
  search: MatchesSearch
  catalog: FacetCatalogEntry[]
  onChange: (patch: Patch) => void
  searchRef?: Ref<HTMLInputElement>
  /** Save / update view controls, shown beside the summary. */
  viewActions?: ReactNode
}

const selectCls =
  "h-7 rounded-md border border-border bg-surface px-2 text-sm text-foreground hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-ink"

/** Matches filter bar (DESIGN 6.1): text search, facet chips, group-by, sort, plain-words summary. */
export function FilterBar({
  search,
  catalog,
  onChange,
  searchRef,
  viewActions,
}: FilterBarProps) {
  const [sheetOpen, setSheetOpen] = useState(false)
  const sels: FacetSels = { f: search.f, r: search.r }
  const setSels = (next: FacetSels) =>
    onChange({ f: next.f, r: next.r, view: search.view })
  const n = activeCount(search)
  const summary = summarise(search, catalog)
  const facets = catalog.filter((e) => e.kind !== "text")
  const groupable = catalog.filter((e) => e.kind === "values")

  const groupSort = (
    <>
      <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <span className="max-md:sr-only">Group</span>
        <select
          aria-label="Group by"
          className={selectCls}
          value={search.g ?? ""}
          onChange={(e) => onChange({ g: e.target.value || undefined })}
        >
          <option value="">No grouping</option>
          {groupable.map((e) => (
            <option key={e.facet} value={e.facet}>
              {e.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <span className="max-md:sr-only">Sort</span>
        <select
          aria-label="Sort"
          className={selectCls}
          value={search.sort ?? DEFAULT_SORT}
          onChange={(e) =>
            onChange({
              sort:
                e.target.value === DEFAULT_SORT ? undefined : e.target.value,
            })
          }
        >
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
    </>
  )

  return (
    <div className="grid gap-2 border-b border-border py-2.5 md:pr-3 md:pl-5.5">
      <div className="flex items-center gap-2">
        <SearchBox
          value={search.q ?? ""}
          onCommit={(q) => onChange({ q: q || undefined })}
          inputRef={searchRef}
        />
        <div className="flex items-center gap-2 max-md:hidden">{groupSort}</div>
        <Button
          variant="outline"
          size="sm"
          className="md:hidden"
          onClick={() => setSheetOpen(true)}
        >
          <SlidersHorizontal data-icon="inline-start" aria-hidden="true" />
          Filters
          {n > 0 && <span className="num text-xs">{n}</span>}
        </Button>
      </div>

      <div
        role="group"
        aria-label="Filters"
        className="flex [scrollbar-width:thin] gap-1.5 overflow-x-auto pb-0.5 max-md:hidden"
      >
        {facets.map((entry) => (
          <FacetButton
            key={entry.facet}
            entry={entry}
            sels={sels}
            onChange={setSels}
          />
        ))}
      </div>

      {(summary || viewActions) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          {summary && (
            <p className="min-w-0 text-muted-foreground" aria-live="polite">
              <span className="sr-only">Showing: </span>
              {summary}
            </p>
          )}
          {n > 0 && (
            <Button
              variant="link"
              size="xs"
              className="px-0"
              onClick={() =>
                onChange({ f: undefined, r: undefined, q: undefined })
              }
            >
              <X data-icon="inline-start" aria-hidden="true" />
              Clear all
            </Button>
          )}
          <div className="ml-auto flex items-center gap-1.5">{viewActions}</div>
        </div>
      )}

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="bottom" className="max-h-[85dvh] gap-3 p-4">
          <SheetHeader className="p-0">
            <SheetTitle className="heading text-md">Filters</SheetTitle>
            <SheetDescription className="text-sm text-muted-foreground">
              Tap a value to include it, again to exclude it, again to clear.
            </SheetDescription>
          </SheetHeader>
          <div className="flex flex-wrap gap-3">{groupSort}</div>
          <div className="min-h-0 overflow-y-auto pb-2">
            <FacetPanel catalog={catalog} sels={sels} onChange={setSels} />
          </div>
          <div className="flex items-center gap-2 border-t border-border pt-3">
            <p className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
              {summary || "No filters"}
            </p>
            {n > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  onChange({ f: undefined, r: undefined, q: undefined })
                }
              >
                Clear all
              </Button>
            )}
            <Button size="sm" onClick={() => setSheetOpen(false)}>
              Done
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}

function SearchBox({
  value,
  onCommit,
  inputRef,
}: {
  value: string
  onCommit: (q: string) => void
  inputRef?: Ref<HTMLInputElement>
}) {
  const [text, setText] = useState(value)
  const timer = useRef<number | undefined>(undefined)
  const last = useRef(value)
  // Follow the URL when it changes from elsewhere (a saved view, Clear all).
  useEffect(() => {
    if (value !== last.current) {
      last.current = value
      setText(value)
    }
  }, [value])
  const commit = (q: string) => {
    window.clearTimeout(timer.current)
    last.current = q.trim()
    onCommit(q.trim())
  }
  return (
    <div className="relative min-w-0 flex-1">
      <Search
        className="pointer-events-none absolute top-1/2 left-2.5 size-[15px] -translate-y-1/2 text-faint"
        aria-hidden="true"
      />
      <input
        ref={inputRef}
        type="search"
        aria-label="Search matches"
        placeholder="Search title, employer, posting"
        value={text}
        onChange={(e) => {
          const q = e.target.value
          setText(q)
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => commit(q), 250)
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit(text)
          if (e.key === "Escape") {
            e.currentTarget.blur()
          }
        }}
        className={cn(
          "h-8 w-full rounded-md border border-border bg-surface pr-9 pl-8 text-sm placeholder:text-faint",
          "field-focus"
        )}
      />
      <KeyHint
        keys="/"
        className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 max-md:hidden"
      />
    </div>
  )
}
