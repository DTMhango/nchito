import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  employerKeys,
  setPolicy,
  type EmployerDetail,
  type EmployerPolicy,
} from "./api"

/** Bounds the server enforces (PolicyIn); checked here first so the owner sees the reason at once. */
export const COOLDOWN_MAX = 3650
export const PRIORITY_MIN = -100
export const PRIORITY_MAX = 100

export type OverrideForm = {
  cooldown: string
  alwaysAsk: boolean
  neverApply: boolean
  neverReason: string
  watched: boolean
  priority: string
  notes: string
}

export function formFrom(d: EmployerDetail): OverrideForm {
  const e = d.employer
  return {
    cooldown: e.cooldown_days === null ? "" : String(e.cooldown_days),
    alwaysAsk: e.always_ask_first,
    neverApply: e.never_apply,
    neverReason: e.never_reason ?? "",
    watched: e.watched,
    priority: String(e.priority),
    notes: d.notes ?? "",
  }
}

const isInt = (s: string) => /^-?\d+$/.test(s.trim())

/** Field errors by field; empty when the form can be saved. Pure, so it is tested alone. */
export function validateOverrides(f: OverrideForm) {
  const errors: Partial<Record<keyof OverrideForm, string>> = {}
  if (f.cooldown.trim() !== "") {
    if (!isInt(f.cooldown) || Number(f.cooldown) < 0)
      errors.cooldown = "Use a whole number of days, 0 or more."
    else if (Number(f.cooldown) > COOLDOWN_MAX)
      errors.cooldown = `Use ${COOLDOWN_MAX} days or fewer.`
  }
  if (!isInt(f.priority)) errors.priority = "Use a whole number."
  else if (
    Number(f.priority) < PRIORITY_MIN ||
    Number(f.priority) > PRIORITY_MAX
  )
    errors.priority = `Use a number from ${PRIORITY_MIN} to ${PRIORITY_MAX}.`
  if (f.neverApply && !f.neverReason.trim())
    errors.neverReason = "Say why you never want to apply here."
  return errors
}

export function toPolicy(f: OverrideForm): EmployerPolicy {
  return {
    cooldown_days: f.cooldown.trim() === "" ? null : Number(f.cooldown),
    always_ask_first: f.alwaysAsk,
    never_apply: f.neverApply,
    never_reason: f.neverApply ? f.neverReason.trim() : null,
    watched: f.watched,
    priority: Number(f.priority),
    notes: f.notes.trim() || null,
  }
}

/** Per-employer overrides: cooldown length, always ask first, never apply (with a reason), watch and priority. */
export function OverridesEditor({
  detail,
  employerKey,
}: {
  detail: EmployerDetail
  employerKey: string
}) {
  const qc = useQueryClient()
  const uid = useId()
  const [form, setForm] = useState<OverrideForm>(() => formFrom(detail))
  const [shown, setShown] = useState(false)
  const errors = validateOverrides(form)
  const set = <K extends keyof OverrideForm>(k: K, v: OverrideForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  const save = useMutation({
    mutationFn: () => setPolicy(employerKey, toPolicy(form)),
    onSuccess: () => {
      toast.success("Saved. The change is in the audit log.")
      void qc.invalidateQueries({ queryKey: employerKeys.all })
      void qc.invalidateQueries({ queryKey: ["matches"] })
      void qc.invalidateQueries({ queryKey: ["applications"] })
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "That did not save."),
  })
  const bad = Object.keys(errors).length > 0
  const err = (k: keyof OverrideForm) =>
    shown && errors[k] ? (
      <p role="alert" className="text-sm text-danger">
        {errors[k]}
      </p>
    ) : null

  return (
    <form
      aria-label="Overrides"
      className="grid gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        setShown(true)
        if (!bad) save.mutate()
      }}
    >
      <div className="grid gap-1.5">
        <label htmlFor={`${uid}-cd`} className="eyebrow">
          Cooldown (days)
        </label>
        <Input
          id={`${uid}-cd`}
          inputMode="numeric"
          className="w-32"
          placeholder={`${detail.cooldown_days} (${detail.cooldown_days_source})`}
          value={form.cooldown}
          onChange={(e) => set("cooldown", e.target.value)}
        />
        <p className="text-sm text-muted-foreground">
          Leave empty to use the default ({detail.cooldown_days_source}).
        </p>
        {err("cooldown")}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={form.alwaysAsk}
          onCheckedChange={(v) => set("alwaysAsk", v === true)}
        />
        Always ask me first
      </label>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={form.watched}
          onCheckedChange={(v) => set("watched", v === true)}
        />
        Watch this employer
      </label>
      <div className="grid gap-1.5">
        <label htmlFor={`${uid}-pr`} className="eyebrow">
          Priority ({PRIORITY_MIN} to {PRIORITY_MAX})
        </label>
        <Input
          id={`${uid}-pr`}
          inputMode="numeric"
          className="w-32"
          value={form.priority}
          onChange={(e) => set("priority", e.target.value)}
        />
        {err("priority")}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={form.neverApply}
          onCheckedChange={(v) => set("neverApply", v === true)}
        />
        Never apply to this employer
      </label>
      {form.neverApply && (
        <div className="grid gap-1.5">
          <label htmlFor={`${uid}-nr`} className="eyebrow">
            Why (required)
          </label>
          <Textarea
            id={`${uid}-nr`}
            rows={2}
            value={form.neverReason}
            onChange={(e) => set("neverReason", e.target.value)}
          />
          {err("neverReason")}
        </div>
      )}
      <div className="grid gap-1.5">
        <label htmlFor={`${uid}-nt`} className="eyebrow">
          Notes
        </label>
        <Textarea
          id={`${uid}-nt`}
          rows={2}
          value={form.notes}
          onChange={(e) => set("notes", e.target.value)}
        />
      </div>
      <div>
        <Button type="submit" disabled={save.isPending}>
          Save overrides
        </Button>
      </div>
    </form>
  )
}
