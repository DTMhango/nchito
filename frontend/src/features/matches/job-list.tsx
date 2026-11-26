import { useEffect, useImperativeHandle, useRef, type Ref } from "react"
import { observeElementRect, useVirtualizer } from "@tanstack/react-virtual"
import { ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import type { EmployerChip } from "@/features/employers/api"
import { valueLabel } from "./filters"
import { JobRow } from "./job-row"
import type { ListRow } from "./use-job-list"

const FALLBACK_RECT = { width: 390, height: 900 }

export type JobListHandle = { scrollToJob: (id: string) => void }

type JobListProps = {
  rows: ListRow[]
  selectedId: string | null
  checked: ReadonlySet<string>
  chips?: Record<string, EmployerChip>
  onOpen: (id: string) => void
  onToggle: (id: string, range: boolean) => void
  onToggleGroup: (value: string) => void
  onEndReached?: () => void
  groupLabel?: string
  footer?: React.ReactNode
  handle?: Ref<JobListHandle>
}

/** The virtualised Matches list. Rows measure themselves, so wrapped chips are fine. */
export function JobList({
  rows,
  selectedId,
  checked,
  chips,
  onOpen,
  onToggle,
  onToggleGroup,
  onEndReached,
  groupLabel,
  footer,
  handle,
}: JobListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const v = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => (rows[i]?.kind === "job" ? 92 : 40),
    getItemKey: (i) => rows[i]?.key ?? i,
    overscan: 10,
    initialRect: FALLBACK_RECT,
    // A list that is not laid out (hidden behind the phone detail, or in tests) still renders
    // its first screen of rows rather than none.
    observeElementRect: (instance, cb) =>
      observeElementRect(instance, (rect) =>
        cb(rect.height > 0 ? rect : FALLBACK_RECT)
      ),
  })

  useImperativeHandle(handle, () => ({
    scrollToJob(id) {
      const i = rows.findIndex((r) => r.kind === "job" && r.job.id === id)
      if (i >= 0) v.scrollToIndex(i, { align: "auto" })
    },
  }))

  const items = v.getVirtualItems()
  const last = items[items.length - 1]
  useEffect(() => {
    if (last && last.index >= rows.length - 8) onEndReached?.()
  }, [last, rows.length, onEndReached])

  const selecting = checked.size > 0
  return (
    <div
      ref={scrollRef}
      className="min-h-0 flex-1 overflow-auto"
      aria-label="Jobs"
      role="region"
    >
      <ul
        className="relative w-full"
        style={{ height: v.getTotalSize() }}
        aria-label="Jobs"
      >
        {items.map((it) => {
          const row = rows[it.index]
          return (
            <li
              key={it.key}
              data-index={it.index}
              ref={v.measureElement}
              className="absolute top-0 left-0 w-full"
              style={{ transform: `translateY(${it.start}px)` }}
            >
              {row.kind === "job" ? (
                <JobRow
                  job={row.job}
                  selected={row.job.id === selectedId}
                  checked={checked.has(row.job.id)}
                  selecting={selecting}
                  employerChip={chips?.[row.job.id]}
                  onOpen={onOpen}
                  onToggle={onToggle}
                />
              ) : row.kind === "group" ? (
                <button
                  type="button"
                  aria-expanded={row.open}
                  onClick={() => onToggleGroup(row.value)}
                  className="flex w-full items-center gap-2 border-b border-border bg-sunken py-2 pr-3.5 pl-5.5 text-left text-sm font-semibold hover:bg-surface-2"
                >
                  <ChevronRight
                    aria-hidden="true"
                    className={cn(
                      "size-4 text-faint transition-transform",
                      row.open && "rotate-90"
                    )}
                  />
                  <span className="min-w-0 truncate">
                    {groupLabel && (
                      <span className="font-normal text-muted-foreground">
                        {groupLabel}:{" "}
                      </span>
                    )}
                    {valueLabel(row.value)}
                  </span>
                  <span className="ml-auto num text-xs font-medium text-faint">
                    {row.count}
                  </span>
                </button>
              ) : (
                <div className="py-3 pr-3.5 pl-5.5 text-sm text-faint">
                  {row.text}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {footer}
    </div>
  )
}
