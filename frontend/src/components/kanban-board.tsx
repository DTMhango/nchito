import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react"
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { cn } from "@/lib/utils"

export type KanbanColumn = { id: string; title: string }

type KanbanBoardProps<T> = {
  columns: KanbanColumn[]
  items: T[]
  getId: (item: T) => string
  getColumn: (item: T) => string
  /** Spoken name of a card, e.g. "Kafue Analytics, Head of Data". */
  getLabel: (item: T) => string
  renderCard: (item: T) => ReactNode
  /**
   * Called when a card is dropped on, or moved by keyboard to, another column.
   * The feature decides what that means (DESIGN 18.2: dragging to Applied opens
   * "I applied myself" instead of creating evidence).
   */
  onMove: (id: string, toColumn: string) => void
  /** Shown inside a column with no cards. */
  emptyColumn?: (column: KanbanColumn) => ReactNode
  className?: string
}

/**
 * Stage board. Drag with a pointer, or focus a card and press Left/Right to move it one
 * column; Up/Down move focus within a column. Moves are announced in a live region.
 */
export function KanbanBoard<T>({
  columns,
  items,
  getId,
  getColumn,
  getLabel,
  renderCard,
  onMove,
  emptyColumn,
  className,
}: KanbanBoardProps<T>) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  )
  const [dragId, setDragId] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState("")
  const refocus = useRef<string | null>(null)
  const boardRef = useRef<HTMLDivElement>(null)
  const helpId = useId()

  const titleOf = (colId: string) =>
    columns.find((c) => c.id === colId)?.title ?? colId
  const byId = (id: string) => items.find((i) => getId(i) === id)

  const move = (id: string, to: string) => {
    const item = byId(id)
    if (!item || getColumn(item) === to) return
    refocus.current = id
    onMove(id, to)
    setAnnouncement(`Moved ${getLabel(item)} to ${titleOf(to)}.`)
  }

  useEffect(() => {
    if (!refocus.current) return
    const el = boardRef.current?.querySelector<HTMLElement>(
      `[data-card-id="${CSS.escape(refocus.current)}"]`
    )
    el?.focus()
    refocus.current = null
  })

  const onKeyDown = (e: KeyboardEvent<HTMLElement>, item: T) => {
    const col = columns.findIndex((c) => c.id === getColumn(item))
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault()
      const next = col + (e.key === "ArrowRight" ? 1 : -1)
      if (next >= 0 && next < columns.length)
        move(getId(item), columns[next].id)
      return
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault()
      const cards = Array.from(
        (
          e.currentTarget.closest("[data-column-id]") as HTMLElement | null
        )?.querySelectorAll<HTMLElement>("[data-card-id]") ?? []
      )
      const idx = cards.indexOf(e.currentTarget as HTMLElement)
      cards[idx + (e.key === "ArrowDown" ? 1 : -1)]?.focus()
    }
  }

  const onDragStart = (e: DragStartEvent) => setDragId(String(e.active.id))
  const onDragEnd = (e: DragEndEvent) => {
    setDragId(null)
    if (e.over) move(String(e.active.id), String(e.over.id))
  }

  const dragging = dragId ? byId(dragId) : undefined

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragId(null)}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) => `Picked up ${labelFor(active.id)}.`,
          onDragOver: ({ active, over }) =>
            over
              ? `${labelFor(active.id)} is over ${titleOf(String(over.id))}.`
              : "",
          onDragEnd: ({ active, over }) =>
            over
              ? `Dropped ${labelFor(active.id)} in ${titleOf(String(over.id))}.`
              : "Dropped.",
          onDragCancel: ({ active }) =>
            `Cancelled moving ${labelFor(active.id)}.`,
        },
      }}
    >
      <div
        ref={boardRef}
        role="list"
        aria-label="Stages"
        className={cn(
          "grid auto-cols-[minmax(236px,1fr)] grid-flow-col items-start gap-3 overflow-x-auto pb-3",
          className
        )}
      >
        {columns.map((col) => {
          const colItems = items.filter((i) => getColumn(i) === col.id)
          return (
            <Column key={col.id} column={col} count={colItems.length}>
              {colItems.map((item) => (
                <Card
                  key={getId(item)}
                  id={getId(item)}
                  helpId={helpId}
                  label={getLabel(item)}
                  onKeyDown={(e) => onKeyDown(e, item)}
                >
                  {renderCard(item)}
                </Card>
              ))}
              {colItems.length === 0 && emptyColumn?.(col)}
            </Column>
          )
        })}
      </div>
      <DragOverlay dropAnimation={null}>
        {dragging ? (
          <div className="rotate-1 rounded-sm shadow-elev">
            {renderCard(dragging)}
          </div>
        ) : null}
      </DragOverlay>
      <span id={helpId} className="sr-only">
        Press left or right arrow to move to another stage, up or down to move
        between cards.
      </span>
      <div aria-live="polite" role="status" className="sr-only">
        {announcement}
      </div>
    </DndContext>
  )

  function labelFor(id: string | number) {
    const item = byId(String(id))
    return item ? getLabel(item) : "card"
  }
}

function Column({
  column,
  count,
  children,
}: {
  column: KanbanColumn
  count: number
  children: ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id: column.id })
  return (
    <div
      ref={setNodeRef}
      role="listitem"
      data-column-id={column.id}
      aria-label={`${column.title}, ${count} ${count === 1 ? "card" : "cards"}`}
      className={cn(
        "grid min-h-[220px] content-start gap-2 rounded-lg bg-sunken p-2.5 transition-shadow",
        isOver && "shadow-[inset_0_0_0_2px_var(--t-primary)]"
      )}
    >
      <div className="flex items-center gap-2 px-1 pt-0.5 pb-1 text-[0.9rem] font-semibold">
        {column.title}
        <span className="num text-xs font-medium text-faint">{count}</span>
      </div>
      {children}
    </div>
  )
}

function Card({
  id,
  helpId,
  label,
  onKeyDown,
  children,
}: {
  id: string
  helpId: string
  label: string
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
  children: ReactNode
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      role="button"
      tabIndex={0}
      data-card-id={id}
      aria-roledescription="card"
      aria-label={label}
      aria-describedby={helpId}
      onKeyDown={(e) => {
        onKeyDown(e)
        if (!e.defaultPrevented) listeners?.onKeyDown?.(e)
      }}
      className={cn(
        "cursor-grab touch-none rounded-sm outline-offset-2",
        isDragging && "opacity-45"
      )}
    >
      {children}
    </div>
  )
}

/** A card body in the mockup's style; use inside renderCard. */
export function KanbanCard({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        "grid gap-2 rounded-sm border border-border bg-surface p-[calc(var(--t-dens)*var(--t-space-k))] text-left transition-[transform,box-shadow] hover:-translate-y-0.5 hover:shadow-elev",
        className
      )}
    >
      {children}
    </div>
  )
}
