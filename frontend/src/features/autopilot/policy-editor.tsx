import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Lock } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { Segmented } from "@/components/segmented"
import { SectionHeader } from "@/components/page-header"
import { NativeSelect } from "@/features/campaigns/bits"
import {
  effectiveMode,
  isModeAllowed,
  LOCK_REASON,
  MODE_ORDER,
  MODES,
  modeCeiling,
} from "@/features/campaigns/automation"
import {
  apKeys,
  campaignsQuery,
  putSetting,
  saveAutomation,
  settingsQuery,
  type AutomationMode,
  type CampaignOut,
  type Channel,
  type SettingOut,
} from "./api"
import {
  CHANNEL_LABEL,
  MODE_LABEL,
  sourceOf,
  validateLimit,
  type LimitKey,
} from "./logic"

const CHANNELS: Channel[] = ["email", "browser", "manual"]

/** Per-campaign policy (mode and channel overrides) plus the limits every campaign shares. */
export function PolicyEditor() {
  const campaigns = useQuery(campaignsQuery())
  const settings = useQuery(settingsQuery())
  const [picked, setPicked] = useState<string | null>(null)
  const list = campaigns.data ?? []
  const campaign = list.find((c) => c.id === picked) ?? list[0]

  return (
    <div className="grid gap-6">
      <section aria-label="Campaign policy" className="grid gap-3">
        <SectionHeader
          title="How far each campaign may go"
          aside="Set on each campaign: its mode and any channel override."
        />
        {list.length > 1 && (
          <label className="grid max-w-xs gap-1 text-sm font-medium">
            Campaign
            <NativeSelect
              value={campaign?.id ?? ""}
              onChange={(e) => setPicked(e.target.value)}
            >
              {list.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          </label>
        )}
        {campaign ? (
          <CampaignPolicy
            key={campaign.id}
            campaign={campaign}
            defaultMode={
              (settings.data?.["automation.default_mode"]?.value as
                AutomationMode | undefined) ?? "prepare"
            }
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            {campaigns.isPending ? "Loading campaigns." : "No campaigns yet."}
          </p>
        )}
      </section>
      <LimitsPanel settings={settings.data} />
    </div>
  )
}

function CampaignPolicy({
  campaign,
  defaultMode,
}: {
  campaign: CampaignOut
  defaultMode: AutomationMode
}) {
  const qc = useQueryClient()
  const ceiling = modeCeiling(campaign)
  const policy = campaign.automation
  const mode = effectiveMode(policy.mode, ceiling)
  const locked = MODE_ORDER.indexOf(ceiling) < MODE_ORDER.length - 1
  const save = useMutation({
    mutationFn: (next: typeof policy) => saveAutomation(campaign, next),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: apKeys.campaigns })
      toast.success(`${campaign.name}: policy saved.`)
    },
    onError: (e) => toast.error(e.message),
  })
  const perChannel = policy.per_channel ?? {}
  const setChannel = (ch: Channel, value: string) => {
    const next = { ...perChannel }
    if (value === "") delete next[ch]
    else next[ch] = value as AutomationMode
    save.mutate({ ...policy, per_channel: next })
  }
  return (
    <div className="grid gap-4 rounded-lg border border-border bg-surface p-4">
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-md">Mode</h4>
          <Chip tone="line">
            Now: {MODE_LABEL[mode]}
            {policy.mode === undefined || policy.mode === null
              ? ` (global default: ${MODE_LABEL[defaultMode]})`
              : " (set on this campaign)"}
          </Chip>
        </div>
        <Segmented
          aria-label="Automation mode"
          value={mode}
          onValueChange={(m) => save.mutate({ ...policy, mode: m })}
          className="max-w-full flex-wrap"
          options={MODES.map((m) => ({
            value: m.value,
            label: m.label,
            disabled: !isModeAllowed(m.value, ceiling),
          }))}
        />
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {MODES.find((m) => m.value === mode)?.line}
        </p>
        {locked && (
          <p
            role="note"
            className="flex items-start gap-2 rounded-md border border-border bg-warn-soft p-2.5 text-sm text-warn"
          >
            <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>{LOCK_REASON}</span>
          </p>
        )}
      </div>
      <div className="grid gap-2">
        <h4 className="text-md">Override by channel</h4>
        <p className="text-sm text-muted-foreground">
          A channel can be stricter than the campaign, for example ask first on
          the browser agent while email applies automatically.
        </p>
        <ul className="grid gap-2 sm:grid-cols-3">
          {CHANNELS.map((ch) => {
            const own = perChannel[ch]
            const eff = effectiveMode(own ?? mode, ceiling)
            return (
              <li key={ch} className="grid gap-1">
                <label htmlFor={`pc-${ch}`} className="text-sm font-medium">
                  {CHANNEL_LABEL[ch]}
                </label>
                <NativeSelect
                  id={`pc-${ch}`}
                  value={own ?? ""}
                  onChange={(e) => setChannel(ch, e.target.value)}
                >
                  <option value="">Same as campaign</option>
                  {MODES.map((m) => (
                    <option
                      key={m.value}
                      value={m.value}
                      disabled={!isModeAllowed(m.value, ceiling)}
                    >
                      {m.label}
                    </option>
                  ))}
                </NativeSelect>
                <span className="text-xs text-faint">
                  Effective: {MODE_LABEL[eff]} ·{" "}
                  {own ? "set for this channel" : "from the campaign"}
                </span>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}

type LimitField = {
  key: LimitKey
  label: string
  hint: string
  unit?: string
}

const LIMITS: { title: string; fields: LimitField[] }[] = [
  {
    title: "Score lines",
    fields: [
      {
        key: "scoring.threshold_shortlist",
        label: "Shortlist from",
        hint: "Roles at or above this are shortlisted.",
        unit: "points",
      },
      {
        key: "scoring.threshold_tailor",
        label: "Tailor documents from",
        hint: "Roles at or above this get a tailored CV and letter.",
        unit: "points",
      },
      {
        key: "scoring.threshold_auto_apply",
        label: "Apply automatically from",
        hint: "Only roles at or above this may go without asking.",
        unit: "points",
      },
    ],
  },
  {
    title: "Caps and cool-down",
    fields: [
      {
        key: "automation.daily_cap",
        label: "Applications a day, at most",
        hint: "Across all campaigns.",
      },
      {
        key: "automation.weekly_cap",
        label: "Applications a week, at most",
        hint: "Must not be below the daily cap.",
      },
      {
        key: "matching.max_live_per_employer",
        label: "Live applications per employer, at most",
        hint: "In flight at one employer at once.",
      },
      {
        key: "matching.employer_cooldown_days",
        label: "Cool-down after applying to an employer",
        hint: "Days before another application there.",
        unit: "days",
      },
    ],
  },
  {
    title: "Quiet hours",
    fields: [
      {
        key: "automation.quiet_hours_start",
        label: "Quiet hours begin",
        hint: "Nothing is sent after this time (your time zone).",
      },
      {
        key: "automation.quiet_hours_end",
        label: "Quiet hours end",
        hint: "Sending may resume at this time.",
      },
    ],
  },
]

function LimitsPanel({
  settings,
}: {
  settings: Record<string, SettingOut> | undefined
}) {
  return (
    <section aria-label="Limits" className="grid gap-3">
      <SectionHeader
        title="Limits for every campaign"
        aside="Global settings, not campaign fields. Each change is recorded in the activity log."
      />
      <p className="max-w-prose text-sm text-muted-foreground">
        Caps, score lines and quiet hours have one value shared by all
        campaigns. A campaign cannot override them. Pausing is not a setting
        here: use the master pause above.
      </p>
      {!settings ? (
        <p className="text-sm text-muted-foreground">Loading limits.</p>
      ) : (
        LIMITS.map((g) => (
          <div key={g.title} className="grid gap-2">
            <h4 className="eyebrow">{g.title}</h4>
            <div className="grid gap-3 sm:grid-cols-2">
              {g.fields.map((f) => (
                <LimitRow
                  key={f.key}
                  field={f}
                  setting={settings[f.key]}
                  all={settings}
                />
              ))}
            </div>
          </div>
        ))
      )}
    </section>
  )
}

function LimitRow({
  field,
  setting,
  all,
}: {
  field: LimitField
  setting: SettingOut | undefined
  all: Record<string, SettingOut>
}) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (value: number | string) => putSetting(field.key, value),
    onSuccess: () => {
      setDraft(null)
      setError(null)
      void qc.invalidateQueries({ queryKey: apKeys.settings })
      toast.success(`${field.label}: saved for every campaign.`)
    },
    onError: (e) => setError(e.message),
  })
  if (!setting) return null
  const shown = draft ?? String(setting.value ?? "")
  const id = `limit-${field.key}`
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const values = Object.fromEntries(
      Object.values(all).map((s) => [s.key, s.value])
    )
    const r = validateLimit(setting, shown, values)
    if (!r.ok) return setError(r.message)
    setError(null)
    save.mutate(r.value)
  }
  const dirty = draft !== null && draft !== String(setting.value ?? "")
  return (
    <form
      onSubmit={submit}
      aria-label={`${field.label}, limit`}
      className="grid content-start gap-1"
    >
      <label htmlFor={id} className="text-sm font-medium">
        {field.label}
      </label>
      <div className="flex gap-2">
        <Input
          id={id}
          inputMode={setting.kind === "time" ? "text" : "numeric"}
          value={shown}
          aria-invalid={error ? true : undefined}
          aria-describedby={`${id}-info`}
          onChange={(e) => {
            setDraft(e.target.value)
            setError(null)
          }}
          className="max-w-32"
        />
        {field.unit && (
          <span className="self-center text-sm text-faint">{field.unit}</span>
        )}
        {dirty && (
          <Button type="submit" size="sm" disabled={save.isPending}>
            Save
          </Button>
        )}
        {dirty && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              setDraft(null)
              setError(null)
            }}
          >
            Undo
          </Button>
        )}
      </div>
      <p id={`${id}-info`} className="text-xs text-faint">
        {field.hint} Effective: {String(setting.value)}
        {field.unit ? ` ${field.unit}` : ""} · {sourceOf(setting)}
        {!setting.is_default && ` · default ${String(setting.default)}`}
      </p>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </form>
  )
}
