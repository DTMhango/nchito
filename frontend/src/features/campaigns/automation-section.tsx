import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Lock } from "lucide-react"
import { toast } from "sonner"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Segmented } from "@/components/segmented"
import { NativeSelect } from "./bits"
import {
  ck,
  employersQuery,
  saveSetting,
  setAlwaysAsk,
  settingsByKey,
  settingsQuery,
} from "./api"
import {
  isModeAllowed,
  LOCK_REASON,
  MODE_ORDER,
  MODES,
  effectiveMode,
} from "./automation"
import type { AutomationMode, AutomationPolicy } from "./types"

type Props = {
  policy: AutomationPolicy
  ceiling: AutomationMode
  onChange: (next: AutomationPolicy) => void
}

export function AutomationSection({ policy, ceiling, onChange }: Props) {
  const mode = effectiveMode(policy.mode, ceiling)
  const locked = MODE_ORDER.indexOf(ceiling) < MODE_ORDER.length - 1
  const line = MODES.find((m) => m.value === mode)?.line

  return (
    <>
      <div className="grid gap-2">
        <h4 className="text-md">How far should it go?</h4>
        <Segmented
          aria-label="Automation mode"
          value={mode}
          onValueChange={(m) => onChange({ ...policy, mode: m })}
          className="max-w-full flex-wrap"
          options={MODES.map((m) => ({
            value: m.value,
            label: m.label,
            disabled: !isModeAllowed(m.value, ceiling),
          }))}
        />
        <p className="text-sm" aria-live="polite">
          {line}
        </p>
        <ul className="grid gap-1 text-sm text-muted-foreground">
          {MODES.map((m) => (
            <li key={m.value}>
              <b className="text-foreground">{m.label}.</b> {m.line}
            </li>
          ))}
        </ul>
        {locked && (
          <p
            className="flex items-start gap-2 rounded-md border border-border bg-warn-soft p-2.5 text-sm text-warn"
            role="note"
          >
            <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>{LOCK_REASON}</span>
          </p>
        )}
      </div>

      <GlobalSettings />
      <AlwaysAsk />
    </>
  )
}

type Field = {
  key: string
  label: string
  hint: string
  kind: "number" | "time" | "choice"
  unit?: string
  choices?: { value: string; label: string }[]
}

const FIELDS: Field[] = [
  {
    key: "automation.daily_cap",
    label: "Applications a day, at most",
    hint: "Across all campaigns.",
    kind: "number",
  },
  {
    key: "automation.weekly_cap",
    label: "Applications a week, at most",
    hint: "Must not be below the daily cap.",
    kind: "number",
  },
  {
    key: "automation.quiet_hours_start",
    label: "Quiet hours begin",
    hint: "Nothing is sent after this time.",
    kind: "time",
  },
  {
    key: "automation.quiet_hours_end",
    label: "Quiet hours end",
    hint: "Sending may resume at this time.",
    kind: "time",
  },
  {
    key: "matching.employer_cooldown_days",
    label: "Wait after applying to an employer",
    hint: "Days before another application to the same employer.",
    kind: "number",
    unit: "days",
  },
  {
    key: "matching.roles_per_employer_scope",
    label: "One role per employer",
    hint: "Which roles at one employer compete, so you do not apply for several.",
    kind: "choice",
    choices: [
      { value: "same_department", label: "Same department" },
      { value: "whole_employer", label: "Whole employer" },
      { value: "off", label: "Off: allow several" },
    ],
  },
  {
    key: "matching.max_live_per_employer",
    label: "Live applications per employer, at most",
    hint: "Applications in flight at one employer.",
    kind: "number",
  },
  {
    key: "matching.conflict_winner",
    label: "When campaigns find the same employer",
    hint: "Who wins when two campaigns each want a different role there.",
    kind: "choice",
    choices: [
      { value: "highest_score", label: "The highest score wins" },
      {
        value: "campaign_priority_then_score",
        label: "Campaign order first, then score",
      },
    ],
  },
]

function GlobalSettings() {
  const qc = useQueryClient()
  const settings = useQuery(settingsQuery())
  const values = settingsByKey(settings.data?.groups)
  const [error, setError] = useState<Record<string, string>>({})

  const commit = async (f: Field, raw: string) => {
    const value = f.kind === "number" ? Number(raw) : raw
    if (String(values[f.key]) === String(value)) return
    if (f.kind === "number" && (raw.trim() === "" || Number.isNaN(value))) {
      setError((e) => ({ ...e, [f.key]: "Enter a number." }))
      return
    }
    try {
      await saveSetting(f.key, value)
      setError((e) => ({ ...e, [f.key]: "" }))
      void qc.invalidateQueries({ queryKey: ck.settings })
      toast.success(`${f.label}: saved for every campaign.`)
    } catch (e) {
      setError((s) => ({
        ...s,
        [f.key]: e instanceof Error ? e.message : "Not saved.",
      }))
    }
  }

  return (
    <div className="grid gap-3">
      <div>
        <h4 className="text-md">Limits and safety</h4>
        <p className="text-sm text-muted-foreground">
          These apply to every campaign, not only this one. Changes save when
          you leave the box and are recorded in the activity log.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => {
          const v = values[f.key]
          const id = `s-${f.key}`
          return (
            <div key={f.key} className="grid content-start gap-1">
              <label htmlFor={id} className="text-sm font-medium">
                {f.label}
              </label>
              {f.kind === "choice" ? (
                <NativeSelect
                  id={id}
                  value={String(v ?? "")}
                  onChange={(e) => void commit(f, e.target.value)}
                >
                  {f.choices!.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </NativeSelect>
              ) : (
                <Input
                  id={id}
                  key={String(v)}
                  type={f.kind === "time" ? "time" : "number"}
                  inputMode={f.kind === "number" ? "numeric" : undefined}
                  defaultValue={v === null || v === undefined ? "" : String(v)}
                  onBlur={(e) => void commit(f, e.target.value)}
                />
              )}
              <p className="text-sm text-muted-foreground">
                {error[f.key] ? (
                  <span className="text-danger" role="alert">
                    {error[f.key]}
                  </span>
                ) : (
                  f.hint
                )}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function AlwaysAsk() {
  const qc = useQueryClient()
  const employers = useQuery(employersQuery())
  const list = employers.data ?? []
  return (
    <div className="grid gap-2">
      <h4 className="text-md">Always ask me first</h4>
      <p className="text-sm text-muted-foreground">
        Employers marked here are never applied to without your approval, even
        in "Apply automatically".
      </p>
      {list.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No watched employers yet. Add them in Sources.
        </p>
      )}
      <ul className="grid gap-1.5">
        {list.map((e) => (
          <li
            key={e.id}
            className="flex items-center gap-3 rounded-md border border-border px-3 py-2"
          >
            <span className="min-w-0 flex-1 truncate">{e.name}</span>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Ask first</span>
              <Switch
                aria-label={`Always ask me before applying to ${e.name}`}
                checked={e.always_ask_first ?? false}
                onCheckedChange={async (on) => {
                  try {
                    await setAlwaysAsk(e, on)
                    void qc.invalidateQueries({ queryKey: ck.employers })
                  } catch {
                    toast.error("Could not change that.")
                  }
                }}
              />
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}
