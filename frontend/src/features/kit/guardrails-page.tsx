import { useState } from "react"
import {
  CheckCircle2,
  FlaskConical,
  Pencil,
  Plus,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Chip } from "@/components/chip"
import { PageHeader, SectionHeader } from "@/components/page-header"
import { Segmented } from "@/components/segmented"
import { Switch } from "@/components/ui/switch"
import {
  useGuardrailCheck,
  useKitList,
  useRemove,
  useSave,
  type GuardrailIn,
  type GuardrailOut,
  type GuardrailScope,
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
  csv,
  GUARDRAIL_TYPE_LABEL,
  GUARDRAIL_TYPES,
  parseCsv,
  SCOPES,
  STRICTNESS,
  summarise,
  type GuardrailType,
} from "./labels"

type Strictness = NonNullable<GuardrailIn["strictness"]>
const STRICT_OPTIONS = (Object.keys(STRICTNESS) as Strictness[]).map(
  (value) => ({
    value,
    label: STRICTNESS[value].label,
  })
)
const DEFAULT_STRICT: Record<GuardrailType, Strictness> = {
  never_mention: "always_block",
  never_together: "always_block",
  omit_field: "always_block",
  attach_policy: "always_block",
  require_wording: "block_waivable_once",
  format: "block_waivable_once",
  limit: "block_waivable_once",
  reframe: "advise",
  positioning: "advise",
}
const TEST_SCOPES: GuardrailScope[] = ["cv", "letter", "email", "form_answers"]

const toIn = (g: GuardrailOut, p: Partial<GuardrailIn> = {}): GuardrailIn => ({
  name: g.name,
  scope: g.scope,
  severity: g.severity,
  strictness: g.strictness,
  params: g.params as GuardrailIn["params"],
  reason: g.reason,
  enabled: g.enabled,
  ...p,
})
const typeOf = (g: GuardrailOut) =>
  ((g.params as { type?: string }).type ?? g.type) as GuardrailType

/** "Test this rule": runs sample text through the checker (the saved rules). */
export function RuleTester({
  ruleId,
  compact,
}: {
  ruleId?: string
  compact?: boolean
}) {
  const check = useGuardrailCheck()
  const [text, setText] = useState("")
  const [scope, setScope] = useState<GuardrailScope>("cv")
  const results = check.data?.results ?? []
  return (
    <section
      aria-label="Test this rule"
      className="grid gap-2 rounded-lg border border-border bg-surface-2 p-3.5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <FlaskConical
          aria-hidden="true"
          className="size-4 text-muted-foreground"
        />
        <h3 className="text-sm font-semibold">
          {compact ? "Test this rule" : "Test the rules"}
        </h3>
        <span className="text-xs text-muted-foreground">
          Runs sample text through the saved rules. Nothing is sent anywhere.
        </span>
      </div>
      <Textarea
        aria-label="Sample text"
        rows={3}
        placeholder="Paste a line from a CV, letter or form answer."
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect
          aria-label="Treat the text as"
          value={scope}
          onChange={(e) => setScope(e.target.value as GuardrailScope)}
        >
          {TEST_SCOPES.map((s) => (
            <option key={s} value={s}>
              As a {SCOPES[s].toLowerCase()}
            </option>
          ))}
        </NativeSelect>
        <Button
          type="button"
          size="sm"
          disabled={!text.trim() || check.isPending}
          onClick={() => check.mutate({ texts: { [scope]: text } })}
        >
          Run check
        </Button>
        {check.isError && (
          <span className="text-sm text-danger">{errorText(check.error)}</span>
        )}
      </div>
      {check.data && (
        <ul aria-label="Check results" className="m-0 grid list-none gap-1 p-0">
          {results.map((r, i) => (
            <li
              key={i}
              className="flex items-start gap-2 rounded-md bg-surface px-2.5 py-1.5 text-sm"
            >
              {r.status === "pass" ? (
                <CheckCircle2
                  aria-hidden="true"
                  className="mt-0.5 size-4 text-good"
                />
              ) : r.status === "warn" ? (
                <TriangleAlert
                  aria-hidden="true"
                  className="mt-0.5 size-4 text-warn"
                />
              ) : (
                <ShieldAlert
                  aria-hidden="true"
                  className="mt-0.5 size-4 text-danger"
                />
              )}
              <span className="min-w-0 flex-1">
                <span className="font-medium">{r.check}</span>
                {r.detail && (
                  <span className="text-muted-foreground">: {r.detail}</span>
                )}
              </span>
              <Chip
                tone={
                  r.status === "pass"
                    ? "good"
                    : r.status === "warn"
                      ? "warn"
                      : "danger"
                }
              >
                {r.status === "pass"
                  ? "Passes"
                  : r.status === "warn"
                    ? "Warning"
                    : "Blocked"}
              </Chip>
              {ruleId && r.guardrail_id === ruleId && (
                <Chip tone="accent">This rule</Chip>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function GuardrailRow({
  g,
  onEdit,
}: {
  g: GuardrailOut
  onEdit: (g: GuardrailOut) => void
}) {
  const save = useSave<GuardrailOut, GuardrailIn>("guardrails")
  const patch = (p: Partial<GuardrailIn>) =>
    save.mutate(
      { id: g.id, body: toIn(g, p) },
      { onError: (e) => toast.error(errorText(e)) }
    )
  return (
    <li
      data-testid={`guardrail-${g.name}`}
      className="grid gap-2 border-t border-border px-3 py-2.5 first:border-t-0"
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <p className="min-w-0 flex-1 font-medium">{summarise(g)}</p>
        <Switch
          checked={g.enabled !== false}
          onCheckedChange={(enabled) => patch({ enabled })}
          aria-label={`${g.name} is on`}
        />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <span className="text-muted-foreground">{g.name}</span>
        {(g.scope ?? []).map((s) => (
          <Chip key={s} tone="line">
            {SCOPES[s]}
          </Chip>
        ))}
        {g.reason && (
          <span className="text-muted-foreground">Why: {g.reason}</span>
        )}
        {g.review_state === "needs_review" && <NeedsReviewChip />}
        <span className="ml-auto flex flex-wrap items-center gap-1.5">
          <Segmented
            size="sm"
            aria-label={`Strictness of ${g.name}`}
            value={g.strictness ?? "always_block"}
            onValueChange={(strictness) =>
              patch({
                strictness,
                severity: strictness === "advise" ? "warn" : "block",
              })
            }
            options={STRICT_OPTIONS}
          />
          {g.review_state === "needs_review" && (
            <ReviewActions
              entity="guardrail"
              id={g.id}
              label={g.name}
              onEdit={() => onEdit(g)}
            />
          )}
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Edit ${g.name}`}
            onClick={() => onEdit(g)}
          >
            <Pencil aria-hidden="true" />
            Edit
          </Button>
        </span>
      </div>
    </li>
  )
}

type Params = Record<string, unknown>

function paramsFor(type: GuardrailType, existing?: Params): Params {
  if (existing && existing.type === type) return { ...existing }
  switch (type) {
    case "never_mention":
      return { type, terms: [], regex: [] }
    case "never_together":
      return { type, group_a: [], group_b: [] }
    case "require_wording":
      return { type, use: "", instead_of: [] }
    case "reframe":
      return { type, prefer: "", over: "" }
    case "omit_field":
      return { type, fields: [] }
    case "format":
      return { type, rule: "", params: {} }
    case "positioning":
      return { type, instruction: "" }
    case "limit":
      return { type, document: "cv", pages: null, paragraphs: null }
    case "attach_policy":
      return { type, document_type: "", when: "when_asked" }
  }
}

function GuardrailDialog({
  open,
  onOpenChange,
  g,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  g: GuardrailOut | null
}) {
  const save = useSave<GuardrailOut, GuardrailIn>("guardrails")
  const remove = useRemove("guardrails")
  const [type, setType] = useState<GuardrailType>(
    g ? typeOf(g) : "never_mention"
  )
  const [p, setP] = useState<Params>(
    paramsFor(type, g?.params as Params | undefined)
  )
  const [name, setName] = useState(g?.name ?? "")
  const [scope, setScope] = useState<GuardrailScope[]>(
    g?.scope?.length ? g.scope : ["everywhere"]
  )
  const [strict, setStrict] = useState<Strictness>(
    g?.strictness ?? DEFAULT_STRICT[type]
  )
  const [reason, setReason] = useState(g?.reason ?? "")
  const set = (k: string, v: unknown) => setP((x) => ({ ...x, [k]: v }))
  const list = (k: string, label: string, hint?: string) => (
    <Field label={label} hint={hint ?? "Separate with commas."}>
      {(id) => (
        <Input
          id={id}
          value={csv(p[k] as string[])}
          onChange={(e) => set(k, parseCsv(e.target.value))}
        />
      )}
    </Field>
  )
  const text = (k: string, label: string, multiline = false) => (
    <Field label={label}>
      {(id) =>
        multiline ? (
          <Textarea
            id={id}
            rows={2}
            value={String(p[k] ?? "")}
            onChange={(e) => set(k, e.target.value)}
          />
        ) : (
          <Input
            id={id}
            value={String(p[k] ?? "")}
            onChange={(e) => set(k, e.target.value)}
          />
        )
      }
    </Field>
  )
  const num = (k: string, label: string) => (
    <Field label={label}>
      {(id) => (
        <Input
          id={id}
          type="number"
          min={1}
          value={p[k] == null ? "" : String(p[k])}
          onChange={(e) =>
            set(k, e.target.value ? Number(e.target.value) : null)
          }
        />
      )}
    </Field>
  )

  // Terms typed with commas would split a phrase; terms are one per comma here by design.
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title={g ? `Edit ${g.name}` : "Add a guardrail"}
      description="A rule the checker enforces over every document and the whole outgoing packet."
      saving={save.isPending}
      error={save.error}
      onSubmit={() => {
        const label = name.trim() || GUARDRAIL_TYPE_LABEL[type].label
        save.mutate(
          {
            id: g?.id,
            body: {
              name: label,
              scope,
              severity: strict === "advise" ? "warn" : "block",
              strictness: strict,
              params: p as GuardrailIn["params"],
              reason: reason.trim() || null,
              enabled: g?.enabled ?? true,
            },
          },
          {
            onSuccess: () => {
              toast.success("Guardrail saved.")
              onOpenChange(false)
            },
          }
        )
      }}
    >
      {!g && (
        <Field label="Kind of rule" hint={GUARDRAIL_TYPE_LABEL[type].blurb}>
          {(id) => (
            <NativeSelect
              id={id}
              value={type}
              onChange={(e) => {
                const t = e.target.value as GuardrailType
                setType(t)
                setP(paramsFor(t))
                setStrict(DEFAULT_STRICT[t])
              }}
            >
              {GUARDRAIL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {GUARDRAIL_TYPE_LABEL[t].label}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
      )}
      <Field label="Name" hint="For your own list. Optional.">
        {(id) => (
          <Input
            id={id}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}
      </Field>

      {type === "never_mention" && (
        <>
          {list("terms", "Never mention these words or phrases")}
          {list(
            "regex",
            "Or these patterns (regular expressions)",
            "Optional. Separate with commas."
          )}
        </>
      )}
      {type === "never_together" && (
        <>
          {list("group_a", "First group")}
          {list("group_b", "Second group")}
        </>
      )}
      {type === "require_wording" && (
        <>
          {text("use", "Always say")}
          {list("instead_of", "Never say instead")}
        </>
      )}
      {type === "reframe" && (
        <>
          {text("prefer", "Prefer")}
          {text("over", "Over")}
        </>
      )}
      {type === "omit_field" && list("fields", "Fields to leave off the CV")}
      {type === "format" && text("rule", "The rule, in plain words", true)}
      {type === "positioning" &&
        text("instruction", "The instruction, in plain words", true)}
      {type === "limit" && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Document">
            {(id) => (
              <NativeSelect
                id={id}
                value={String(p.document)}
                onChange={(e) => set("document", e.target.value)}
              >
                <option value="cv">CV</option>
                <option value="letter">Letter</option>
                <option value="email">Email</option>
              </NativeSelect>
            )}
          </Field>
          {num("pages", "Most pages")}
          {num("paragraphs", "Most paragraphs")}
        </div>
      )}
      {type === "attach_policy" && (
        <div className="grid gap-3 sm:grid-cols-2">
          {text("document_type", "Document type, e.g. degree")}
          <Field label="Attach it">
            {(id) => (
              <NativeSelect
                id={id}
                value={String(p.when)}
                onChange={(e) => set("when", e.target.value)}
              >
                <option value="never">Never</option>
                <option value="when_asked">Only when asked</option>
                <option value="after_offer">Only after an offer</option>
              </NativeSelect>
            )}
          </Field>
        </div>
      )}

      <fieldset className="grid gap-1.5">
        <legend className="mb-1 text-sm font-medium">Applies to</legend>
        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(SCOPES) as GuardrailScope[]).map((s) => (
            <PillToggle
              key={s}
              pressed={scope.includes(s)}
              onPressedChange={(on) =>
                setScope((cur) => {
                  const next = on ? [...cur, s] : cur.filter((x) => x !== s)
                  return next.length ? next : cur
                })
              }
            >
              {SCOPES[s]}
            </PillToggle>
          ))}
        </div>
      </fieldset>
      <Field label="How strict" hint={STRICTNESS[strict].hint}>
        {() => (
          <Segmented
            aria-label="Strictness"
            value={strict}
            onValueChange={setStrict}
            options={STRICT_OPTIONS}
          />
        )}
      </Field>
      <Field label="Reason" hint="Shown when the rule fires. Optional.">
        {(id) => (
          <Input
            id={id}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        )}
      </Field>
      {g && <RuleTester ruleId={g.id} compact />}
      {g && (
        <div>
          <ConfirmButton
            label="Delete this guardrail"
            onConfirm={() =>
              remove.mutate(g.id, {
                onSuccess: () => {
                  toast.success("Guardrail deleted.")
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

/** Kit, Guardrails (DESIGN 5.3). */
export function GuardrailsPage() {
  const rules = useKitList<GuardrailOut>("guardrails")
  const [search, setSearch] = useState("")
  const [reviewOnly, setReviewOnly] = useState(false)
  const [dialog, setDialog] = useState<{ g: GuardrailOut | null } | null>(null)
  const review = useReviewFor("guardrails")
  const q = search.trim().toLowerCase()

  return (
    <div>
      <PageHeader
        title="Guardrails"
        description="Rules the checker enforces over every document and the whole outgoing packet. Code checks first, a model second, and passing the code check is what counts."
        actions={
          <Button size="sm" onClick={() => setDialog({ g: null })}>
            <Plus aria-hidden="true" />
            Add a guardrail
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
          label="Search guardrails"
          placeholder="Search guardrails"
        />
      </div>
      <div className="grid gap-6">
        <QueryGate query={rules}>
          {(all) => {
            const shown = all.filter(
              (g) =>
                (!reviewOnly || g.review_state === "needs_review") &&
                (!q ||
                  `${g.name} ${summarise(g)} ${g.reason ?? ""}`
                    .toLowerCase()
                    .includes(q))
            )
            if (shown.length === 0)
              return (
                <ListEmpty>
                  {all.length === 0
                    ? "No guardrails yet. Start with things you must never say, like a confidential figure or a tool you never used."
                    : "No guardrails match."}
                </ListEmpty>
              )
            return (
              <>
                {GUARDRAIL_TYPES.map((t) => {
                  const rows = shown.filter((g) => typeOf(g) === t)
                  if (rows.length === 0) return null
                  return (
                    <section key={t} aria-label={GUARDRAIL_TYPE_LABEL[t].label}>
                      <SectionHeader
                        as="h3"
                        title={GUARDRAIL_TYPE_LABEL[t].label}
                        aside={GUARDRAIL_TYPE_LABEL[t].blurb}
                      />
                      <ul className="m-0 list-none overflow-hidden rounded-lg border border-border bg-surface p-0">
                        {rows.map((g) => (
                          <GuardrailRow
                            key={g.id}
                            g={g}
                            onEdit={(x) => setDialog({ g: x })}
                          />
                        ))}
                      </ul>
                    </section>
                  )
                })}
              </>
            )
          }}
        </QueryGate>
        <RuleTester />
      </div>
      {dialog && (
        <GuardrailDialog
          key={dialog.g?.id ?? "new"}
          open
          onOpenChange={(o) => !o && setDialog(null)}
          g={dialog.g}
        />
      )}
    </div>
  )
}
