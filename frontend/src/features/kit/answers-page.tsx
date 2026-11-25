import { useMemo, useState } from "react"
import { CalendarClock, Pencil, Plus } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip, type ChipTone } from "@/components/chip"
import { PageHeader } from "@/components/page-header"
import {
  useKitList,
  useRemove,
  useSave,
  type AnswerIn,
  type AnswerOut,
} from "./api"
import {
  ConfirmButton,
  errorText,
  Field,
  FormDialog,
  ListEmpty,
  NativeSelect,
  NeedsReviewChip,
  PillToggle,
  QueryGate,
  ReviewActions,
  ReviewBanner,
  SearchBox,
  useReviewFor,
} from "./common"
import {
  ANSWER_CLASS,
  ANSWER_SCOPE,
  csv,
  fmtDate,
  parseCsv,
  VALUE_TYPES,
} from "./labels"

type Cls = NonNullable<AnswerOut["answer_class"]>
type Cond = {
  type: string
  facet?: string
  include?: string[]
  [k: string]: unknown
}
type Group = { type: "group"; op: string; negate: boolean; conditions: Cond[] }

const CLASS_TONE: Record<Cls, ChipTone> = {
  auto: "good",
  ask_first: "warn",
  never: "danger",
  owner_only: "info",
}

/** The three condition facets the owner edits in plain fields. Anything else is preserved. */
const COND_FACETS = [
  {
    facet: "country",
    label: "Country",
    hint: "Country codes, like ZM, separated with commas.",
  },
  {
    facet: "employment_type",
    label: "Employment type",
    hint: "Like permanent, contract.",
  },
  {
    facet: "employer",
    label: "Employer",
    hint: "Employer names, separated with commas.",
  },
] as const

const groupOf = (a: AnswerOut | AnswerIn): Group =>
  ((a.conditions as { root?: Group } | undefined)?.root ?? {
    type: "group",
    op: "and",
    negate: false,
    conditions: [],
  }) as Group

const condText = (a: AnswerOut) =>
  COND_FACETS.flatMap(({ facet, label }) => {
    const c = groupOf(a).conditions.find(
      (x) => x.type === "values" && x.facet === facet
    )
    return c?.include?.length ? [`${label}: ${c.include.join(", ")}`] : []
  })

const isDue = (a: AnswerOut) =>
  !!a.review_after && new Date(a.review_after).getTime() <= Date.now()

function AnswerRow({
  a,
  onEdit,
}: {
  a: AnswerOut
  onEdit: (a: AnswerOut) => void
}) {
  const cls = a.answer_class ?? "auto"
  const conds = condText(a)
  const due = isDue(a)
  return (
    <li
      data-testid={`answer-${a.id}`}
      className="grid gap-1.5 border-t border-border px-3 py-2.5 first:border-t-0"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{a.patterns.canonical}</p>
          {(a.patterns.variants ?? []).length > 0 && (
            <p className="text-sm text-muted-foreground">
              Also asked as: {(a.patterns.variants ?? []).join("; ")}
            </p>
          )}
        </div>
        <div className="max-w-[40%] min-w-24 text-right">
          {a.value ? (
            <span className="font-medium">{a.value}</span>
          ) : (
            <span className="text-faint">
              {cls === "never" ? a.forced_choice || "No answer" : "No value"}
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <Chip tone={CLASS_TONE[cls]} title={ANSWER_CLASS[cls].hint}>
          {ANSWER_CLASS[cls].label}
        </Chip>
        <Chip tone="line">{ANSWER_SCOPE[a.scope ?? "this_application"]}</Chip>
        {conds.map((c) => (
          <Chip key={c} tone="primary">
            {c}
          </Chip>
        ))}
        {a.review_state === "needs_review" && <NeedsReviewChip />}
        {a.confirmed_at && (
          <span className="text-muted-foreground">
            Confirmed {fmtDate(a.confirmed_at)}
          </span>
        )}
        {a.review_after && (
          <Chip tone={due ? "warn" : "neutral"} icon={CalendarClock}>
            {due ? "Review due" : "Review"} {fmtDate(a.review_after)}
          </Chip>
        )}
        {!!a.pending_applications_using && (
          <span className="text-muted-foreground">
            Used by {a.pending_applications_using} pending application
            {a.pending_applications_using === 1 ? "" : "s"}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1">
          {a.review_state === "needs_review" && (
            <ReviewActions
              entity="answer"
              id={a.id}
              label={a.patterns.canonical}
              onEdit={() => onEdit(a)}
            />
          )}
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Edit ${a.patterns.canonical}`}
            onClick={() => onEdit(a)}
          >
            <Pencil aria-hidden="true" />
            Edit
          </Button>
        </span>
      </div>
    </li>
  )
}

function AnswerDialog({
  open,
  onOpenChange,
  a,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  a: AnswerOut | null
}) {
  const save = useSave<AnswerOut, AnswerIn>("answers")
  const remove = useRemove("answers")
  const [canonical, setCanonical] = useState(a?.patterns.canonical ?? "")
  const [variants, setVariants] = useState(
    (a?.patterns.variants ?? []).join("\n")
  )
  const [value, setValue] = useState(a?.value ?? "")
  const [valueType, setValueType] = useState<
    NonNullable<AnswerIn["value_type"]>
  >(a?.value_type ?? "text")
  const [cls, setCls] = useState<Cls>(a?.answer_class ?? "ask_first")
  const [scope, setScope] = useState<NonNullable<AnswerIn["scope"]>>(
    a?.scope ?? "all_matching"
  )
  const [forced, setForced] = useState(a?.forced_choice ?? "")
  const [reviewAfter, setReviewAfter] = useState(
    (a?.review_after ?? "").slice(0, 10)
  )
  const [settled, setSettled] = useState(!!a?.settled)
  const [material, setMaterial] = useState(!!a?.material)
  const existing = a
    ? groupOf(a)
    : { type: "group", op: "and", negate: false, conditions: [] as Cond[] }
  const [conds, setConds] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      COND_FACETS.map(({ facet }) => [
        facet,
        csv(
          existing.conditions.find(
            (c) => c.type === "values" && c.facet === facet
          )?.include
        ),
      ])
    )
  )

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title={a ? "Edit answer" : "Add an answer"}
      description="A question answered once and reused. Material answers ask first."
      saving={save.isPending}
      error={save.error}
      onSubmit={() => {
        if (!canonical.trim()) return
        const kept = existing.conditions.filter(
          (c) =>
            !(
              c.type === "values" &&
              COND_FACETS.some((f) => f.facet === c.facet)
            )
        )
        const mine: Cond[] = COND_FACETS.flatMap(({ facet }) => {
          const include = parseCsv(conds[facet] ?? "")
          return include.length
            ? [{ type: "values", facet, include, exclude: [], match: "any" }]
            : []
        })
        save.mutate(
          {
            id: a?.id,
            body: {
              patterns: {
                canonical: canonical.trim(),
                variants: variants
                  .split("\n")
                  .map((v) => v.trim())
                  .filter(Boolean),
              },
              value: value.trim() || null,
              value_type: valueType,
              answer_class: cls,
              scope,
              forced_choice: cls === "never" ? forced.trim() || null : null,
              review_after: reviewAfter || null,
              settled,
              material,
              conditions: {
                version: 1,
                root: { ...existing, conditions: [...kept, ...mine] },
              } as AnswerIn["conditions"],
            },
          },
          {
            onSuccess: () => {
              toast.success("Answer saved.")
              onOpenChange(false)
            },
          }
        )
      }}
    >
      <Field label="Question">
        {(id) => (
          <Input
            id={id}
            autoFocus
            required
            value={canonical}
            onChange={(e) => setCanonical(e.target.value)}
          />
        )}
      </Field>
      <Field label="Other ways it is asked" hint="One per line.">
        {(id) => (
          <Textarea
            id={id}
            rows={2}
            value={variants}
            onChange={(e) => setVariants(e.target.value)}
          />
        )}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="How it is used" hint={ANSWER_CLASS[cls].hint}>
          {(id) => (
            <NativeSelect
              id={id}
              value={cls}
              onChange={(e) => setCls(e.target.value as Cls)}
            >
              {(Object.keys(ANSWER_CLASS) as Cls[]).map((c) => (
                <option key={c} value={c}>
                  {ANSWER_CLASS[c].label}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field label="Where it applies">
          {(id) => (
            <NativeSelect
              id={id}
              value={scope}
              onChange={(e) => setScope(e.target.value as typeof scope)}
            >
              {Object.entries(ANSWER_SCOPE).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        {cls !== "never" && cls !== "owner_only" && (
          <>
            <Field label="Answer">
              {(id) => (
                <Input
                  id={id}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              )}
            </Field>
            <Field label="Answer type">
              {(id) => (
                <NativeSelect
                  id={id}
                  value={valueType}
                  onChange={(e) =>
                    setValueType(e.target.value as typeof valueType)
                  }
                >
                  {Object.entries(VALUE_TYPES).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          </>
        )}
        {cls === "never" && (
          <Field
            label="If a form forces a choice"
            hint="For example: Prefer not to say."
          >
            {(id) => (
              <Input
                id={id}
                value={forced}
                onChange={(e) => setForced(e.target.value)}
              />
            )}
          </Field>
        )}
      </div>
      <fieldset className="grid gap-2 rounded-md border border-border p-3">
        <legend className="px-1 text-sm font-medium">
          Only when (leave empty for always)
        </legend>
        <div className="grid gap-3 sm:grid-cols-3">
          {COND_FACETS.map(({ facet, label, hint }) => (
            <Field key={facet} label={label} hint={hint}>
              {(id) => (
                <Input
                  id={id}
                  value={conds[facet] ?? ""}
                  onChange={(e) =>
                    setConds((c) => ({ ...c, [facet]: e.target.value }))
                  }
                />
              )}
            </Field>
          ))}
        </div>
      </fieldset>
      <div className="grid items-end gap-3 sm:grid-cols-2">
        <Field
          label="Review again on"
          hint="Optional. Only applications that use it pause when it falls due."
        >
          {(id) => (
            <Input
              id={id}
              type="date"
              value={reviewAfter}
              onChange={(e) => setReviewAfter(e.target.value)}
            />
          )}
        </Field>
        <div className="flex flex-wrap gap-2 pb-5">
          <PillToggle pressed={material} onPressedChange={setMaterial}>
            Material (pay, work rights)
          </PillToggle>
          <PillToggle pressed={settled} onPressedChange={setSettled}>
            Settled
          </PillToggle>
        </div>
      </div>
      {a && (
        <div>
          <ConfirmButton
            label="Delete this answer"
            onConfirm={() =>
              remove.mutate(a.id, {
                onSuccess: () => {
                  toast.success("Answer deleted.")
                  onOpenChange(false)
                },
                onError: (e) => toast.error(errorText(e)),
              })
            }
          />
        </div>
      )}
    </FormDialog>
  )
}

/** Kit, Answer bank (DESIGN 5.4). */
export function AnswersPage() {
  const answers = useKitList<AnswerOut>("answers")
  const [search, setSearch] = useState("")
  const [cls, setCls] = useState<"" | Cls>("")
  const [dueOnly, setDueOnly] = useState(false)
  const [reviewOnly, setReviewOnly] = useState(false)
  const [dialog, setDialog] = useState<{ a: AnswerOut | null } | null>(null)
  const review = useReviewFor("answers")
  const dueCount = (answers.data ?? []).filter(isDue).length

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (answers.data ?? []).filter(
      (a) =>
        (!cls || a.answer_class === cls) &&
        (!dueOnly || isDue(a)) &&
        (!reviewOnly || a.review_state === "needs_review") &&
        (!q ||
          `${a.patterns.canonical} ${(a.patterns.variants ?? []).join(" ")} ${a.value ?? ""}`
            .toLowerCase()
            .includes(q))
    )
  }, [answers.data, search, cls, dueOnly, reviewOnly])

  return (
    <div>
      <PageHeader
        title="Answer bank"
        description="Application questions answered once and reused. Material answers, like pay and work rights, ask you first."
        actions={
          <Button size="sm" onClick={() => setDialog({ a: null })}>
            <Plus aria-hidden="true" />
            Add an answer
          </Button>
        }
      />
      <ReviewBanner
        count={review.count}
        only={reviewOnly}
        onOnlyChange={setReviewOnly}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SearchBox
          value={search}
          onChange={setSearch}
          label="Search answers"
          placeholder="Search answers"
        />
        <NativeSelect
          aria-label="Filter by how it is used"
          value={cls}
          onChange={(e) => setCls(e.target.value as "" | Cls)}
        >
          <option value="">Any use</option>
          {(Object.keys(ANSWER_CLASS) as Cls[]).map((c) => (
            <option key={c} value={c}>
              {ANSWER_CLASS[c].label}
            </option>
          ))}
        </NativeSelect>
        <PillToggle pressed={dueOnly} onPressedChange={setDueOnly}>
          Due for review{dueCount > 0 ? ` (${dueCount})` : ""}
        </PillToggle>
      </div>
      <QueryGate query={answers}>
        {(all) =>
          rows.length === 0 ? (
            <ListEmpty>
              {all.length === 0
                ? "No answers yet. Add the questions every form asks, like notice period and work rights."
                : "No answers match."}
            </ListEmpty>
          ) : (
            <ul
              aria-label="Answers"
              className="m-0 list-none overflow-hidden rounded-lg border border-border bg-surface p-0"
            >
              {rows.map((a) => (
                <AnswerRow
                  key={a.id}
                  a={a}
                  onEdit={(x) => setDialog({ a: x })}
                />
              ))}
            </ul>
          )
        }
      </QueryGate>
      {dialog && (
        <AnswerDialog
          key={dialog.a?.id ?? "new"}
          open
          onOpenChange={(o) => !o && setDialog(null)}
          a={dialog.a}
        />
      )}
    </div>
  )
}
