import { useMemo, useState, type ReactNode } from "react"
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react"
import { cn } from "@/lib/utils"

export type Column<T> = {
  id: string
  header: ReactNode
  cell: (row: T) => ReactNode
  /** Return a value to make the column sortable. */
  sortValue?: (row: T) => string | number
  align?: "left" | "right"
  className?: string
  /** Hide below this breakpoint. */
  hideBelow?: "sm" | "md" | "lg"
}

type SortState = { id: string; dir: "asc" | "desc" } | null

type DataTableProps<T> = {
  columns: Column<T>[]
  rows: T[]
  getRowId: (row: T) => string
  caption?: string
  /** Shown in place of the body when there are no rows. */
  empty?: ReactNode
  onRowClick?: (row: T) => void
  initialSort?: SortState
  minWidth?: number
  className?: string
}

const HIDE = { sm: "max-sm:hidden", md: "max-md:hidden", lg: "max-lg:hidden" }

/**
 * Flat table with hairlines and label-style headers (mockup `.tbl`). Sortable columns use
 * buttons in the header with aria-sort; rows with onRowClick are keyboard reachable.
 */
export function DataTable<T>({
  columns,
  rows,
  getRowId,
  caption,
  empty,
  onRowClick,
  initialSort = null,
  minWidth,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<SortState>(initialSort)

  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.id === sort.id)
    if (!col?.sortValue) return rows
    const get = col.sortValue
    return [...rows].sort((a, b) => {
      const va = get(a)
      const vb = get(b)
      const r =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb))
      return sort.dir === "asc" ? r : -r
    })
  }, [rows, sort, columns])

  const toggle = (id: string) =>
    setSort((s) =>
      s?.id === id
        ? s.dir === "asc"
          ? { id, dir: "desc" }
          : null
        : { id, dir: "asc" }
    )

  return (
    <div className={cn("overflow-x-auto border-t border-border", className)}>
      <table
        className="w-full border-collapse text-[0.88rem]"
        style={minWidth ? { minWidth } : undefined}
      >
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.id === c.id
              return (
                <th
                  key={c.id}
                  scope="col"
                  aria-sort={
                    active
                      ? sort!.dir === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                  className={cn(
                    "border-b border-border py-2 pr-2.5 text-left eyebrow text-[0.7rem] whitespace-nowrap",
                    c.align === "right" && "text-right",
                    c.hideBelow && HIDE[c.hideBelow]
                  )}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggle(c.id)}
                      className="inline-flex items-center gap-1 rounded-xs [letter-spacing:inherit] [text-transform:inherit] hover:text-foreground"
                    >
                      {c.header}
                      {active ? (
                        sort!.dir === "asc" ? (
                          <ArrowUp className="size-3" aria-hidden="true" />
                        ) : (
                          <ArrowDown className="size-3" aria-hidden="true" />
                        )
                      ) : (
                        <ChevronsUpDown
                          className="size-3 opacity-50"
                          aria-hidden="true"
                        />
                      )}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && empty ? (
            <tr>
              <td colSpan={columns.length} className="border-b border-border">
                {empty}
              </td>
            </tr>
          ) : (
            sorted.map((row) => (
              <tr
                key={getRowId(row)}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter") onRowClick(row)
                      }
                    : undefined
                }
                className={cn(
                  onRowClick &&
                    "cursor-pointer hover:bg-surface-2 focus-visible:bg-surface-2"
                )}
              >
                {columns.map((c) => (
                  <td
                    key={c.id}
                    className={cn(
                      "border-b border-border row-pad-sm pr-2.5 align-top",
                      c.align === "right" && "text-right",
                      c.hideBelow && HIDE[c.hideBelow],
                      c.className
                    )}
                  >
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
