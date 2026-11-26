import type { ReactNode } from "react"
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  BookPlus,
  GripVertical,
  Plus,
  Quote,
  Trash2,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { FactTag } from "@/components/fact-tag"
import { cn } from "@/lib/utils"
import type { FactOut } from "./api"
import {
  move,
  newKey,
  traceClaim,
  type DraftItem,
  type FactIndex,
} from "./draft"

export type ClaimContext = {
  index: FactIndex
  /** Approved facts the owner may cite. */
  citable: FactOut[]
  /** Turn an untraced claim into a draft fact in the Kit (DESIGN 9.4). */
  onAddToLibrary: (item: DraftItem) => void
  addingKey: string | null
}

export const claimDomId = (key: string) => `claim-${key}`

/** What is wrong with a claim's tracing, in words; empty when it is sound. */
function TraceFlags({ item, index }: { item: DraftItem; index: FactIndex }) {
  if (!item.text.trim()) return null
  const t = traceClaim(item, index)
  const flags: ReactNode[] = []
  if (t.state === "untraced")
    flags.push(
      <Chip key="u" tone="danger" icon={AlertTriangle} data-flag="untraced">
        Untraced: no fact behind this claim
      </Chip>
    )
  for (const f of t.facts.filter((x) => x.status !== "approved"))
    flags.push(
      <Chip key={`s-${f.id}`} tone="warn" icon={AlertTriangle}>
        {f.code} is {f.status === "draft" ? "a draft, not approved" : "retired"}
      </Chip>
    )
  for (const m of t.missing)
    flags.push(
      <Chip key={`m-${m}`} tone="warn" icon={AlertTriangle}>
        {m} is not in your Kit
      </Chip>
    )
  if (t.strayFigures.length)
    flags.push(
      <Chip key="f" tone="warn" icon={AlertTriangle}>
        {t.strayFigures.map((n) => `"${n}"`).join(", ")} not in its facts
      </Chip>
    )
  return flags.length ? (
    <div className="flex flex-wrap gap-1.5" aria-live="polite">
      {flags}
    </div>
  ) : null
}

type ClaimEditorProps = {
  item: DraftItem
  /** Accessible name: "Summary", "Bullet 3, Head of Finance Operations". */
  label: string
  ctx: ClaimContext
  onChange: (next: DraftItem) => void
  /** Single-line fields (the headline). */
  short?: boolean
  /** Reorder controls and the grip, for list items. */
  order?: {
    index: number
    total: number
    onMove: (to: number) => void
    handle: ReactNode
  }
  onRemove?: () => void
}

/**
 * One claim: the wording, the facts it rests on (hover or focus a tag to read the fact),
 * and anything wrong with its tracing. Untraced claims carry a danger edge and chip.
 */
export function ClaimEditor({
  item,
  label,
  ctx,
  onChange,
  short,
  order,
  onRemove,
}: ClaimEditorProps) {
  const trace = traceClaim(item, ctx.index)
  const untraced = trace.state === "untraced" && !!item.text.trim()
  const single = trace.facts.length === 1 ? trace.facts[0] : null
  const options = ctx.citable.filter(
    (f) => !item.fact_ids.includes(f.id) && !item.fact_ids.includes(f.code)
  )
  const id = claimDomId(item.key)

  return (
    <div
      role="group"
      aria-label={label}
      data-claim={item.key}
      data-trace={untraced ? "untraced" : trace.state}
      className={cn(
        "grid gap-2 rounded-md border border-border bg-surface p-2.5 transition-shadow focus-within:border-primary focus-within:ring-3 focus-within:ring-ring",
        untraced && "border-l-4 border-l-danger",
        order && "grid-cols-[22px_minmax(0,1fr)]"
      )}
    >
      {order && <div className="pt-1">{order.handle}</div>}
      <div className="grid min-w-0 gap-2">
        <label htmlFor={id} className="sr-only">
          {label}
        </label>
        <textarea
          id={id}
          rows={short ? 1 : 2}
          value={item.text}
          onChange={(e) => onChange({ ...item, text: e.target.value })}
          className={cn(
            "field-sizing-content w-full resize-none border-0 bg-transparent p-0.5 leading-[1.45] text-foreground outline-none placeholder:text-faint",
            short ? "min-h-7 text-[1.02rem] font-medium" : "min-h-10"
          )}
          placeholder="Write the claim, then cite the fact it rests on"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          {trace.facts.map((f) => (
            <span key={f.id} className="inline-flex items-center">
              <FactTag
                code={f.code}
                text={f.text}
                status={f.status as "approved" | "draft" | "retired"}
              />
              <button
                type="button"
                aria-label={`Stop citing ${f.code} here`}
                onClick={() =>
                  onChange({
                    ...item,
                    fact_ids: item.fact_ids.filter(
                      (x) => x !== f.id && x !== f.code
                    ),
                  })
                }
                className="ml-0.5 grid size-5 place-items-center rounded-full text-faint hover:bg-sunken hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary-ink"
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            </span>
          ))}
          {options.length > 0 && (
            <select
              aria-label={`Cite a fact for: ${label}`}
              value=""
              onChange={(e) =>
                e.target.value &&
                onChange({
                  ...item,
                  fact_ids: [...item.fact_ids, e.target.value],
                })
              }
              className="h-6 max-w-[11rem] rounded-full border border-dashed field-focus border-border bg-transparent px-2 text-xs text-muted-foreground hover:border-border-strong"
            >
              <option value="">Cite a fact…</option>
              {options.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.code}: {f.text.slice(0, 60)}
                  {f.text.length > 60 ? "…" : ""}
                </option>
              ))}
            </select>
          )}
          <span className="ml-auto flex items-center gap-0.5">
            {single && single.text !== item.text && (
              <Button
                size="icon-xs"
                variant="ghost"
                aria-label={`Use the wording of ${single.code}`}
                title={`Use the wording of ${single.code}`}
                onClick={() => onChange({ ...item, text: single.text })}
              >
                <Quote aria-hidden="true" />
              </Button>
            )}
            {untraced && (
              <Button
                size="xs"
                variant="ghost"
                disabled={ctx.addingKey === item.key}
                onClick={() => ctx.onAddToLibrary(item)}
              >
                <BookPlus aria-hidden="true" />
                Add to my library
              </Button>
            )}
            {order && (
              <>
                <Button
                  size="icon-xs"
                  variant="ghost"
                  aria-label={`Move ${label} up`}
                  disabled={order.index === 0}
                  onClick={() => order.onMove(order.index - 1)}
                >
                  <ArrowUp aria-hidden="true" />
                </Button>
                <Button
                  size="icon-xs"
                  variant="ghost"
                  aria-label={`Move ${label} down`}
                  disabled={order.index === order.total - 1}
                  onClick={() => order.onMove(order.index + 1)}
                >
                  <ArrowDown aria-hidden="true" />
                </Button>
              </>
            )}
            {onRemove && (
              <Button
                size="icon-xs"
                variant="ghost"
                aria-label={`Remove ${label}`}
                onClick={onRemove}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            )}
          </span>
        </div>
        <TraceFlags item={item} index={ctx.index} />
      </div>
    </div>
  )
}

function SortableClaim(
  props: Omit<ClaimEditorProps, "order"> & {
    index: number
    total: number
    onMove: (to: number) => void
  }
) {
  const { index, total, onMove, ...rest } = props
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: props.item.key })
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(isDragging && "relative z-10 opacity-80")}
    >
      <ClaimEditor
        {...rest}
        order={{
          index,
          total,
          onMove,
          handle: (
            <button
              type="button"
              ref={setActivatorNodeRef}
              {...attributes}
              {...listeners}
              aria-label={`Reorder ${props.label}. Press space, then the arrow keys.`}
              className="grid size-[22px] cursor-grab touch-none place-items-center rounded-sm text-faint hover:bg-sunken hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary-ink active:cursor-grabbing"
            >
              <GripVertical className="size-4" aria-hidden="true" />
            </button>
          ),
        }}
      />
    </li>
  )
}

/** A reorderable list of claims (bullets, competencies, letter paragraphs). */
export function ClaimList({
  items,
  labelFor,
  ctx,
  onChange,
  addLabel,
  listLabel,
}: {
  items: DraftItem[]
  labelFor: (i: number) => string
  ctx: ClaimContext
  onChange: (next: DraftItem[]) => void
  addLabel: string
  listLabel: string
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return
    const from = items.findIndex((x) => x.key === e.active.id)
    const to = items.findIndex((x) => x.key === e.over!.id)
    onChange(move(items, from, to))
  }
  return (
    <div className="grid gap-2">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
      >
        <SortableContext
          items={items.map((x) => x.key)}
          strategy={verticalListSortingStrategy}
        >
          <ol aria-label={listLabel} className="m-0 grid list-none gap-2 p-0">
            {items.map((it, i) => (
              <SortableClaim
                key={it.key}
                item={it}
                label={labelFor(i)}
                ctx={ctx}
                index={i}
                total={items.length}
                onMove={(to) => onChange(move(items, i, to))}
                onChange={(next) =>
                  onChange(items.map((x) => (x.key === it.key ? next : x)))
                }
                onRemove={() => onChange(items.filter((x) => x.key !== it.key))}
              />
            ))}
          </ol>
        </SortableContext>
      </DndContext>
      <Button
        size="sm"
        variant="ghost"
        className="justify-self-start"
        onClick={() =>
          onChange([...items, { key: newKey(), text: "", fact_ids: [] }])
        }
      >
        <Plus aria-hidden="true" />
        {addLabel}
      </Button>
    </div>
  )
}
