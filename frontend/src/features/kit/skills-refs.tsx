import { useState } from "react"
import { Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { Segmented } from "@/components/segmented"
import {
  useKitList,
  useRemove,
  useSave,
  type ReferenceIn,
  type ReferenceOut,
  type SkillAliasOut,
  type SkillIn,
  type SkillOut,
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
  ReviewActions,
} from "./common"
import { CLAIMS, SHARE_POLICY } from "./labels"

const toIn = (s: SkillOut): SkillIn => ({
  name: s.name,
  group: s.group,
  level: s.level,
  claim: s.claim,
  note: s.note,
})

type Claim = NonNullable<SkillOut["claim"]>
const CLAIM_OPTIONS = (Object.keys(CLAIMS) as Claim[]).map((value) => ({
  value,
  label: value === "yes" ? "Yes" : value === "no" ? "No" : "Never",
}))

function SkillRow({
  skill,
  aliases,
}: {
  skill: SkillOut
  aliases: SkillAliasOut[]
}) {
  const save = useSave<SkillOut, SkillIn>("skills")
  const remove = useRemove("skills")
  const saveAlias = useSave<
    SkillAliasOut,
    { alias: string; canonical: string }
  >("skill-aliases")
  const removeAlias = useRemove("skill-aliases")
  const [newAlias, setNewAlias] = useState("")
  const patch = (p: Partial<SkillIn>) =>
    save.mutate(
      { id: skill.id, body: { ...toIn(skill), ...p } },
      { onError: (e) => toast.error(errorText(e)) }
    )
  const blurSave =
    (key: "group" | "level") => (e: React.FocusEvent<HTMLInputElement>) => {
      const v = e.target.value.trim() || null
      if (v !== (skill[key] ?? null)) patch({ [key]: v })
    }
  return (
    <li
      data-testid={`skill-${skill.name}`}
      className="grid gap-2 border-t border-border px-3 py-2.5 first:border-t-0 md:grid-cols-[minmax(0,1.3fr)_9rem_8rem_auto] md:items-center"
    >
      <div className="grid gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{skill.name}</span>
          {skill.review_state === "needs_review" && <NeedsReviewChip />}
          {skill.claim === "never" && (
            <Chip tone="danger" title="Fed to the checker as a never-claim">
              Never claim
            </Chip>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {aliases.map((a) => (
            <Chip key={a.id} tone="line">
              {a.alias}
              <button
                type="button"
                aria-label={`Remove alias ${a.alias}`}
                className="-mr-1 rounded-full hover:text-danger"
                onClick={() => removeAlias.mutate(a.id)}
              >
                <X aria-hidden="true" />
              </button>
            </Chip>
          ))}
          <input
            aria-label={`Add an alias for ${skill.name}`}
            placeholder="Add alias"
            value={newAlias}
            onChange={(e) => setNewAlias(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newAlias.trim()) {
                e.preventDefault()
                saveAlias.mutate(
                  { body: { alias: newAlias.trim(), canonical: skill.name } },
                  { onSuccess: () => setNewAlias("") }
                )
              }
            }}
            className="h-6 w-24 rounded-sm border border-transparent bg-transparent px-1 text-xs outline-none placeholder:text-faint hover:border-border focus:border-input focus:bg-surface"
          />
        </div>
      </div>
      <Input
        aria-label={`Group of ${skill.name}`}
        placeholder="Group"
        defaultValue={skill.group ?? ""}
        onBlur={blurSave("group")}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        className="h-7"
      />
      <Input
        aria-label={`Level of ${skill.name}`}
        placeholder="Level"
        defaultValue={skill.level ?? ""}
        onBlur={blurSave("level")}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        className="h-7"
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <Segmented
          size="sm"
          aria-label={`Claim ${skill.name}`}
          value={skill.claim ?? "yes"}
          onValueChange={(claim) => patch({ claim })}
          options={CLAIM_OPTIONS}
        />
        {skill.review_state === "needs_review" && (
          <ReviewActions entity="skill" id={skill.id} label={skill.name} />
        )}
        <ConfirmButton
          label=""
          confirmLabel="Sure?"
          onConfirm={() => remove.mutate(skill.id)}
        />
      </div>
    </li>
  )
}

export function SkillsTab({
  search,
  reviewOnly,
}: {
  search: string
  reviewOnly: boolean
}) {
  const skills = useKitList<SkillOut>("skills")
  const aliases = useKitList<SkillAliasOut>("skill-aliases")
  const save = useSave<SkillOut, SkillIn>("skills")
  const [name, setName] = useState("")
  const [claim, setClaim] = useState<"all" | Claim>("all")
  const q = search.trim().toLowerCase()
  const all = skills.data ?? []
  const rows = all
    .filter((s) => (claim === "all" ? true : s.claim === claim))
    .filter((s) => !reviewOnly || s.review_state === "needs_review")
    .filter((s) => {
      if (!q) return true
      const al = (aliases.data ?? []).filter((a) => a.canonical === s.name)
      return `${s.name} ${s.group ?? ""} ${al.map((a) => a.alias).join(" ")}`
        .toLowerCase()
        .includes(q)
    })
    .sort(
      (a, b) =>
        (a.group ?? "~").localeCompare(b.group ?? "~") ||
        a.name.localeCompare(b.name)
    )

  const add = () => {
    const n = name.trim()
    if (!n) return
    save.mutate(
      { body: { name: n, claim: "yes" } },
      {
        onSuccess: () => setName(""),
        onError: (e) => toast.error(errorText(e)),
      }
    )
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            add()
          }}
        >
          <Input
            aria-label="New skill"
            placeholder="Add a skill, then press Enter"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-64"
          />
          <Button
            type="submit"
            size="sm"
            disabled={!name.trim() || save.isPending}
          >
            <Plus aria-hidden="true" />
            Add skill
          </Button>
        </form>
        <span
          className="ml-auto flex flex-wrap gap-1.5"
          role="group"
          aria-label="Filter by claim"
        >
          <PillToggle
            pressed={claim === "all"}
            onPressedChange={() => setClaim("all")}
          >
            All
          </PillToggle>
          {CLAIM_OPTIONS.map((o) => (
            <PillToggle
              key={o.value}
              pressed={claim === o.value}
              onPressedChange={(v) => setClaim(v ? o.value : "all")}
            >
              {CLAIMS[o.value]}
            </PillToggle>
          ))}
        </span>
      </div>
      {rows.length === 0 ? (
        <ListEmpty>
          {all.length === 0
            ? "No skills yet. Add the ones you would stand behind in an interview, and mark the ones you must never claim."
            : "No skills match."}
        </ListEmpty>
      ) : (
        <ul
          aria-label="Skills"
          className="m-0 list-none overflow-hidden rounded-lg border border-border bg-surface p-0"
        >
          {rows.map((s) => (
            <SkillRow
              key={s.id}
              skill={s}
              aliases={(aliases.data ?? []).filter(
                (a) => a.canonical === s.name
              )}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// References
// ---------------------------------------------------------------------------

const refToIn = (r: ReferenceOut): ReferenceIn => ({
  name: r.name,
  role: r.role,
  organisation: r.organisation,
  contact_email: r.contact_email,
  contact_phone: r.contact_phone,
  consent: r.consent,
  share_policy: r.share_policy,
})

function ReferenceDialog({
  open,
  onOpenChange,
  ref_,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  ref_: ReferenceOut | null
}) {
  const save = useSave<ReferenceOut, ReferenceIn>("references")
  const [r, setR] = useState<ReferenceIn>(
    ref_
      ? refToIn(ref_)
      : { name: "", consent: false, share_policy: "on_request" }
  )
  const set = <K extends keyof ReferenceIn>(k: K, v: ReferenceIn[K]) =>
    setR((p) => ({ ...p, [k]: v }))
  const text = (
    k: "role" | "organisation" | "contact_email" | "contact_phone",
    label: string
  ) => (
    <Field label={label}>
      {(id) => (
        <Input
          id={id}
          value={r[k] ?? ""}
          onChange={(e) => set(k, e.target.value || null)}
        />
      )}
    </Field>
  )
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={ref_ ? `Edit ${ref_.name}` : "Add a reference"}
      saving={save.isPending}
      error={save.error}
      onSubmit={() => {
        if (!r.name.trim()) return
        save.mutate(
          { id: ref_?.id, body: { ...r, name: r.name.trim() } },
          {
            onSuccess: () => {
              toast.success("Reference saved.")
              onOpenChange(false)
            },
          }
        )
      }}
    >
      <Field label="Name">
        {(id) => (
          <Input
            id={id}
            autoFocus
            required
            value={r.name}
            onChange={(e) => set("name", e.target.value)}
          />
        )}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        {text("role", "Role")}
        {text("organisation", "Organisation")}
        {text("contact_email", "Email")}
        {text("contact_phone", "Phone")}
      </div>
      <Field label="When may we share them?">
        {(id) => (
          <NativeSelect
            id={id}
            value={r.share_policy ?? "on_request"}
            onChange={(e) =>
              set("share_policy", e.target.value as ReferenceIn["share_policy"])
            }
          >
            {Object.entries(SHARE_POLICY).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </NativeSelect>
        )}
      </Field>
      <div>
        <PillToggle
          pressed={!!r.consent}
          onPressedChange={(v) => set("consent", v)}
        >
          They have agreed to be a referee
        </PillToggle>
      </div>
    </FormDialog>
  )
}

export function ReferencesTab({
  search,
  reviewOnly,
}: {
  search: string
  reviewOnly: boolean
}) {
  const refs = useKitList<ReferenceOut>("references")
  const save = useSave<ReferenceOut, ReferenceIn>("references")
  const remove = useRemove("references")
  const [dialog, setDialog] = useState<{ ref: ReferenceOut | null } | null>(
    null
  )
  const q = search.trim().toLowerCase()
  const rows = (refs.data ?? [])
    .filter((r) => !reviewOnly || r.review_state === "needs_review")
    .filter(
      (r) =>
        !q ||
        `${r.name} ${r.role ?? ""} ${r.organisation ?? ""}`
          .toLowerCase()
          .includes(q)
    )
  return (
    <div className="grid gap-3">
      <div>
        <Button size="sm" onClick={() => setDialog({ ref: null })}>
          <Plus aria-hidden="true" />
          Add a reference
        </Button>
      </div>
      {rows.length === 0 ? (
        <ListEmpty>
          {(refs.data ?? []).length === 0
            ? "No references yet. Add people who have agreed to speak for you."
            : "No references match."}
        </ListEmpty>
      ) : (
        <ul
          aria-label="References"
          className="m-0 list-none overflow-hidden rounded-lg border border-border bg-surface p-0"
        >
          {rows.map((r) => (
            <li
              key={r.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border px-3 py-2.5 first:border-t-0"
            >
              <div className="min-w-0 flex-1">
                <div className="font-medium">{r.name}</div>
                <div className="text-sm text-muted-foreground">
                  {[r.role, r.organisation].filter(Boolean).join(", ")}
                </div>
              </div>
              <PillToggle
                pressed={!!r.consent}
                onPressedChange={(v) =>
                  save.mutate({ id: r.id, body: { ...refToIn(r), consent: v } })
                }
                aria-label={`Consent from ${r.name}`}
              >
                Agreed
              </PillToggle>
              <Chip tone={r.consent ? "neutral" : "warn"}>
                {r.consent
                  ? SHARE_POLICY[r.share_policy ?? "on_request"]
                  : "Do not share"}
              </Chip>
              {r.review_state === "needs_review" && (
                <>
                  <NeedsReviewChip />
                  <ReviewActions
                    entity="reference"
                    id={r.id}
                    label={r.name}
                    onEdit={() => setDialog({ ref: r })}
                  />
                </>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDialog({ ref: r })}
                aria-label={`Edit ${r.name}`}
              >
                Edit
              </Button>
              <ConfirmButton onConfirm={() => remove.mutate(r.id)} />
            </li>
          ))}
        </ul>
      )}
      {dialog && (
        <ReferenceDialog
          key={dialog.ref?.id ?? "new"}
          open
          onOpenChange={(o) => !o && setDialog(null)}
          ref_={dialog.ref}
        />
      )}
    </div>
  )
}
