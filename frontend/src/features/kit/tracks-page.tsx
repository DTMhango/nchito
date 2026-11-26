import { useState } from "react"
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
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { ArrowDown, ArrowUp, GripVertical, Pencil, Plus } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { FactTag } from "@/components/fact-tag"
import { PageHeader } from "@/components/page-header"
import { cn } from "@/lib/utils"
import {
  useKitList,
  useRemove,
  useSave,
  type FactOut,
  type TrackIn,
  type TrackOut,
} from "./api"
import {
  ConfirmButton,
  errorText,
  Field,
  FormDialog,
  ListEmpty,
  NativeSelect,
  NeedsReviewChip,
  QueryGate,
  ReviewActions,
  ReviewBanner,
  SearchBox,
  useReviewFor,
} from "./common"
import { csv, parseCsv } from "./labels"

const toIn = (t: TrackOut, priority = t.priority): TrackIn => ({
  key: t.key,
  name: t.name,
  priority,
  example_titles: t.example_titles,
  lead_fact_codes: t.lead_fact_codes,
  summary_fact_code: t.summary_fact_code,
  tone_notes: t.tone_notes,
})

function TrackRow({
  track,
  index,
  total,
  facts,
  onEdit,
  onMove,
}: {
  track: TrackOut
  index: number
  total: number
  facts: FactOut[]
  onEdit: (t: TrackOut) => void
  onMove: (from: number, to: number) => void
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: track.id })
  const lead = (track.lead_fact_codes ?? [])
    .map((c) => facts.find((f) => f.code === c))
    .filter((f): f is FactOut => !!f)
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-testid={`track-${track.key}`}
      className={cn(
        "grid grid-cols-[auto_auto_1fr] gap-x-2.5 gap-y-2 border-t border-border bg-surface px-3 py-3 first:border-t-0",
        isDragging && "relative z-10 elev rounded-md border"
      )}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Reorder ${track.name}. Press space, then the arrow keys.`}
        className="mt-0.5 flex size-7 cursor-grab touch-none items-center justify-center rounded-sm text-faint hover:bg-sunken hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary-ink active:cursor-grabbing"
      >
        <GripVertical aria-hidden="true" className="size-4" />
      </button>
      <span className="mt-1 w-5 text-right num text-lg font-semibold text-muted-foreground">
        {index + 1}
      </span>
      <div className="grid min-w-0 gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 className="text-base font-semibold">{track.name}</h3>
          <code className="num text-xs text-faint">{track.key}</code>
          {track.review_state === "needs_review" && <NeedsReviewChip />}
          <span className="ml-auto flex flex-wrap items-center gap-1">
            {track.review_state === "needs_review" && (
              <ReviewActions
                entity="track"
                id={track.id}
                label={track.name}
                onEdit={() => onEdit(track)}
              />
            )}
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label={`Move ${track.name} up`}
              disabled={index === 0}
              onClick={() => onMove(index, index - 1)}
            >
              <ArrowUp aria-hidden="true" />
            </Button>
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label={`Move ${track.name} down`}
              disabled={index === total - 1}
              onClick={() => onMove(index, index + 1)}
            >
              <ArrowDown aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Edit ${track.name}`}
              onClick={() => onEdit(track)}
            >
              <Pencil aria-hidden="true" />
              Edit
            </Button>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="eyebrow">Example titles</span>
          {(track.example_titles ?? []).length === 0 && (
            <span className="text-faint">None yet</span>
          )}
          {(track.example_titles ?? []).map((t) => (
            <Chip key={t} tone="line">
              {t}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="eyebrow">Lead with</span>
          {lead.length === 0 && (
            <span className="text-faint">No lead facts chosen</span>
          )}
          {lead.map((f) => (
            <FactTag key={f.id} code={f.code} text={f.text} status={f.status} />
          ))}
        </div>
        {track.tone_notes && (
          <p className="text-sm text-muted-foreground">{track.tone_notes}</p>
        )}
      </div>
    </li>
  )
}

function TrackDialog({
  open,
  onOpenChange,
  track,
  facts,
  nextPriority,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  track: TrackOut | null
  facts: FactOut[]
  nextPriority: number
}) {
  const save = useSave<TrackOut, TrackIn>("tracks")
  const remove = useRemove("tracks")
  const [name, setName] = useState(track?.name ?? "")
  const [key, setKey] = useState(track?.key ?? "")
  const [titles, setTitles] = useState(csv(track?.example_titles))
  const [lead, setLead] = useState<string[]>(track?.lead_fact_codes ?? [])
  const [summary, setSummary] = useState(track?.summary_fact_code ?? "")
  const [tone, setTone] = useState(track?.tone_notes ?? "")
  const [pick, setPick] = useState("")
  const usable = facts.filter((f) => f.status !== "retired")
  const q = pick.trim().toLowerCase()
  const candidates = usable.filter(
    (f) => !q || `${f.code} ${f.text}`.toLowerCase().includes(q)
  )
  const move = (i: number, d: number) => setLead((l) => arrayMove(l, i, i + d))
  const toggle = (code: string) =>
    setLead((l) =>
      l.includes(code) ? l.filter((c) => c !== code) : [...l, code]
    )
  const textOf = (code: string) =>
    facts.find((f) => f.code === code)?.text ?? ""

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title={track ? `Edit ${track.name}` : "Add a track"}
      description="A track is a positioning. It picks which facts lead and which titles you may use. It never edits a fact."
      saving={save.isPending}
      error={save.error}
      onSubmit={() => {
        if (!name.trim()) return
        const k = (
          key.trim() ||
          name
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
        ).replace(/^-|-$/g, "")
        save.mutate(
          {
            id: track?.id,
            body: {
              key: k,
              name: name.trim(),
              priority: track?.priority ?? nextPriority,
              example_titles: parseCsv(titles),
              lead_fact_codes: lead,
              summary_fact_code: summary || null,
              tone_notes: tone.trim() || null,
            },
          },
          {
            onSuccess: () => {
              toast.success("Track saved.")
              onOpenChange(false)
            },
          }
        )
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name">
          {(id) => (
            <Input
              id={id}
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
        <Field
          label="Key"
          hint="Short and lowercase. Facts refer to a track by this."
        >
          {(id) => (
            <Input
              id={id}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              disabled={!!track}
            />
          )}
        </Field>
      </div>
      <Field
        label="Example job titles"
        hint="Separate with commas. Used to judge how well a job fits."
      >
        {(id) => (
          <Input
            id={id}
            value={titles}
            onChange={(e) => setTitles(e.target.value)}
          />
        )}
      </Field>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">
          Lead with these facts
        </legend>
        {lead.length > 0 && (
          <ol className="m-0 grid list-none gap-1 p-0">
            {lead.map((code, i) => (
              <li
                key={code}
                className="flex items-center gap-2 rounded-md border border-border bg-sunken px-2 py-1 text-sm"
              >
                <span className="num font-semibold">{code}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  {textOf(code)}
                </span>
                <Button
                  type="button"
                  size="icon-xs"
                  variant="ghost"
                  aria-label={`Move ${code} up`}
                  disabled={i === 0}
                  onClick={() => move(i, -1)}
                >
                  <ArrowUp aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  size="icon-xs"
                  variant="ghost"
                  aria-label={`Move ${code} down`}
                  disabled={i === lead.length - 1}
                  onClick={() => move(i, 1)}
                >
                  <ArrowDown aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ol>
        )}
        <Input
          aria-label="Search facts to lead with"
          placeholder="Search facts"
          value={pick}
          onChange={(e) => setPick(e.target.value)}
        />
        <ul className="m-0 max-h-44 list-none overflow-y-auto rounded-md border border-border p-0">
          {candidates.map((f) => (
            <li key={f.id}>
              <label className="flex cursor-pointer items-start gap-2 px-2 py-1.5 text-sm hover:bg-sunken">
                <input
                  type="checkbox"
                  className="mt-1 accent-[var(--t-primary)]"
                  checked={lead.includes(f.code)}
                  onChange={() => toggle(f.code)}
                />
                <span className="num font-semibold">{f.code}</span>
                <span className="min-w-0 flex-1">{f.text}</span>
              </label>
            </li>
          ))}
          {candidates.length === 0 && (
            <li className="px-2 py-3 text-sm text-muted-foreground">
              No facts match.
            </li>
          )}
        </ul>
      </fieldset>
      <Field label="Opening summary">
        {(id) => (
          <NativeSelect
            id={id}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
          >
            <option value="">No summary fact</option>
            {usable
              .filter((f) => f.kind === "summary")
              .map((f) => (
                <option key={f.id} value={f.code}>
                  {f.code}: {f.text.slice(0, 60)}
                </option>
              ))}
          </NativeSelect>
        )}
      </Field>
      <Field label="Tone notes">
        {(id) => (
          <Textarea
            id={id}
            rows={2}
            value={tone}
            onChange={(e) => setTone(e.target.value)}
          />
        )}
      </Field>
      {track && (
        <div>
          <ConfirmButton
            label="Delete this track"
            onConfirm={() =>
              remove.mutate(track.id, {
                onSuccess: () => {
                  toast.success("Track deleted.")
                  onOpenChange(false)
                },
              })
            }
          />
        </div>
      )}
    </FormDialog>
  )
}

/** Kit, Tracks (DESIGN 5.2): priority order by drag, lead-with facts, example titles. */
export function TracksPage() {
  const tracks = useKitList<TrackOut>("tracks")
  const facts = useKitList<FactOut>("facts")
  const save = useSave<TrackOut, TrackIn>("tracks")
  const [override, setOverride] = useState<TrackOut[] | null>(null)
  const [search, setSearch] = useState("")
  const [reviewOnly, setReviewOnly] = useState(false)
  const [dialog, setDialog] = useState<{ track: TrackOut | null } | null>(null)
  const review = useReviewFor("tracks")
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  const order =
    override ??
    [...(tracks.data ?? [])].sort(
      (a, b) => (a.priority ?? 0) - (b.priority ?? 0)
    )

  /** Show the new order at once, save the changed priorities, then trust the server again. */
  const persist = (next: TrackOut[]) => {
    setOverride(next)
    const changed = next.flatMap((t, i) =>
      (t.priority ?? 0) !== i + 1
        ? [save.mutateAsync({ id: t.id, body: toIn(t, i + 1) })]
        : []
    )
    Promise.all(changed)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setOverride(null))
  }
  const move = (from: number, to: number) => persist(arrayMove(order, from, to))
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return
    const from = order.findIndex((t) => t.id === e.active.id)
    const to = order.findIndex((t) => t.id === e.over!.id)
    if (from >= 0 && to >= 0) move(from, to)
  }

  const q = search.trim().toLowerCase()
  const filtering = !!q || reviewOnly
  const rows = order.filter(
    (t) =>
      (!reviewOnly || t.review_state === "needs_review") &&
      (!q ||
        `${t.name} ${t.key} ${(t.example_titles ?? []).join(" ")}`
          .toLowerCase()
          .includes(q))
  )

  return (
    <div>
      <PageHeader
        title="Tracks"
        description="A track is a positioning: which facts lead, which titles are allowed, which summary opens. Drag to set priority; the first track wins when a job fits more than one."
        actions={
          <Button size="sm" onClick={() => setDialog({ track: null })}>
            <Plus aria-hidden="true" />
            Add a track
          </Button>
        }
      />
      <ReviewBanner
        count={review.count}
        only={reviewOnly}
        onOnlyChange={setReviewOnly}
      />
      <div className="mb-4">
        <SearchBox
          value={search}
          onChange={setSearch}
          label="Search tracks"
          placeholder="Search tracks"
        />
      </div>
      <QueryGate query={tracks}>
        {() =>
          rows.length === 0 ? (
            <ListEmpty>
              {order.length === 0
                ? "No tracks yet. Add one for each kind of role you want to be considered for."
                : "No tracks match."}
            </ListEmpty>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={onDragEnd}
            >
              <SortableContext
                items={rows.map((t) => t.id)}
                strategy={verticalListSortingStrategy}
              >
                <ol
                  aria-label="Tracks in priority order"
                  className="m-0 list-none overflow-hidden rounded-lg border border-border p-0"
                >
                  {rows.map((t) => (
                    <TrackRow
                      key={t.id}
                      track={t}
                      index={order.findIndex((x) => x.id === t.id)}
                      total={order.length}
                      facts={facts.data ?? []}
                      onEdit={(x) => setDialog({ track: x })}
                      onMove={filtering ? () => undefined : move}
                    />
                  ))}
                </ol>
              </SortableContext>
            </DndContext>
          )
        }
      </QueryGate>
      {dialog && (
        <TrackDialog
          key={dialog.track?.id ?? "new"}
          open
          onOpenChange={(o) => !o && setDialog(null)}
          track={dialog.track}
          facts={facts.data ?? []}
          nextPriority={order.length + 1}
        />
      )}
    </div>
  )
}
