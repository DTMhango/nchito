import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Chip, type ChipTone } from "@/components/chip"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Field, NativeSelect } from "./bits"
import { employersQuery, sourcesQuery } from "./api"
import { UNKNOWN_CHOICES, UNKNOWN_FIELDS } from "./automation"
import type {
  CampaignBudget,
  Source,
  UnknownChoice,
  UnknownDataPolicy,
} from "./types"

/** (3) When information is missing. */
export function UnknownSection({
  policy,
  onChange,
}: {
  policy: UnknownDataPolicy
  onChange: (next: UnknownDataPolicy) => void
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {UNKNOWN_FIELDS.map((f) => (
        <Field
          key={f.key}
          label={f.label}
          htmlFor={`unknown-${f.key}`}
          hint={f.plain}
        >
          <NativeSelect
            id={`unknown-${f.key}`}
            value={policy[f.key] ?? ""}
            onChange={(e) =>
              onChange({
                ...policy,
                [f.key]: (e.target.value || null) as UnknownChoice | null,
              })
            }
          >
            {UNKNOWN_CHOICES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
      ))}
      <p className="text-sm text-muted-foreground sm:col-span-2">
        "Unknown" never counts as "yes". Whatever you choose, a role with
        unknown pay, eligibility or deadline is not applied to automatically
        unless the answer is found.
      </p>
    </div>
  )
}

const HEALTH: Record<string, ChipTone> = {
  ok: "good",
  degraded: "warn",
  failing: "danger",
  unknown: "neutral",
}
const HEALTH_WORDS: Record<string, string> = {
  ok: "Working",
  degraded: "Slow",
  failing: "Failing",
  unknown: "Not checked yet",
}

/** (6) Sources. */
export function SourcesSection({
  selected,
  onChange,
}: {
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  const sources = useQuery(sourcesQuery())
  const employers = useQuery(employersQuery())
  const list: Source[] = sources.data ?? []
  return (
    <>
      <div className="grid gap-2">
        <h4 className="text-md">Where to look</h4>
        {list.length === 0 && !sources.isLoading && (
          <p className="text-sm text-muted-foreground">
            No sources set up yet. Add some in{" "}
            <Link to="/sources" className="text-primary-ink underline">
              Sources
            </Link>
            .
          </p>
        )}
        <ul className="grid gap-1.5">
          {list.map((s) => {
            const on = selected.includes(s.id)
            return (
              <li
                key={s.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border px-3 py-2"
              >
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{s.name}</span>{" "}
                  <span className="text-sm text-muted-foreground">
                    {s.connector.replaceAll("_", " ")}
                  </span>
                </span>
                {s.enabled === false && <Chip tone="line">Switched off</Chip>}
                <Chip tone={HEALTH[s.health.status ?? "unknown"]}>
                  {HEALTH_WORDS[s.health.status ?? "unknown"]}
                </Chip>
                <Switch
                  aria-label={`Use ${s.name} in this campaign`}
                  checked={on}
                  onCheckedChange={(v) =>
                    onChange(
                      v
                        ? [...selected, s.id]
                        : selected.filter((x) => x !== s.id)
                    )
                  }
                />
              </li>
            )
          })}
        </ul>
      </div>
      <div className="grid gap-1.5">
        <h4 className="text-md">Watched employers</h4>
        <p className="text-sm text-muted-foreground">
          Employers you watch are checked on their own career boards and feed
          every campaign. Manage them in{" "}
          <Link to="/sources" className="text-primary-ink underline">
            Sources
          </Link>
          .
        </p>
        <div className="flex flex-wrap gap-1.5">
          {(employers.data ?? []).map((e) => (
            <Chip key={e.id} tone="line">
              {e.name}
            </Chip>
          ))}
        </div>
      </div>
    </>
  )
}

const CRON_DAILY = /^(\d{1,2}) (\d{1,2}) \* \* (\*|1-5)$/

export function parseDailyCron(
  cron: string | null | undefined
): { time: string; weekdays: boolean } | null {
  const m = cron ? CRON_DAILY.exec(cron.trim()) : null
  if (!m) return null
  const mm = Number(m[1])
  const hh = Number(m[2])
  if (mm > 59 || hh > 23) return null
  return {
    time: `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`,
    weekdays: m[3] === "1-5",
  }
}

export function buildDailyCron(time: string, weekdays: boolean): string {
  const [h, m] = time.split(":").map(Number)
  return `${m || 0} ${h || 0} * * ${weekdays ? "1-5" : "*"}`
}

/** (7) Schedule and budget. */
export function ScheduleBudgetSection({
  cron,
  defaultCron,
  onCron,
  budget,
  onBudget,
  currency,
}: {
  cron: string | null
  defaultCron: string | null
  onCron: (c: string | null) => void
  budget: CampaignBudget
  onBudget: (b: CampaignBudget) => void
  currency: string
}) {
  const parsed = parseDailyCron(cron)
  const custom = cron !== null
  const major = (m: number | null | undefined) =>
    m === null || m === undefined ? "" : String(m / 100)
  const minor = (s: string) =>
    s.trim() === "" ? null : Math.round(Number(s) * 100)
  const defaultParsed = parseDailyCron(defaultCron)
  return (
    <>
      <div className="grid gap-2">
        <h4 className="text-md">When it looks for roles</h4>
        <label className="flex items-center gap-2 text-sm">
          <Switch
            aria-label="Use a schedule just for this campaign"
            checked={custom}
            onCheckedChange={(on) =>
              onCron(
                on
                  ? buildDailyCron(defaultParsed?.time ?? "06:00", false)
                  : null
              )
            }
          />
          Use its own schedule
        </label>
        {!custom ? (
          <p className="text-sm text-muted-foreground">
            Following the general schedule
            {defaultParsed
              ? `: every day at ${defaultParsed.time}`
              : defaultCron
                ? ` (${defaultCron})`
                : ""}
            , in your time zone.
          </p>
        ) : parsed ? (
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Time of day" htmlFor="sched-time">
              <Input
                id="sched-time"
                type="time"
                className="w-36"
                value={parsed.time}
                onChange={(e) =>
                  onCron(
                    buildDailyCron(e.target.value || "06:00", parsed.weekdays)
                  )
                }
              />
            </Field>
            <Field label="Days" htmlFor="sched-days">
              <NativeSelect
                id="sched-days"
                value={parsed.weekdays ? "weekdays" : "daily"}
                onChange={(e) =>
                  onCron(
                    buildDailyCron(parsed.time, e.target.value === "weekdays")
                  )
                }
              >
                <option value="daily">Every day</option>
                <option value="weekdays">Monday to Friday</option>
              </NativeSelect>
            </Field>
          </div>
        ) : (
          <Field
            label="Schedule (cron)"
            htmlFor="sched-cron"
            hint="A custom schedule that the simple picker cannot show."
          >
            <Input
              id="sched-cron"
              value={cron ?? ""}
              onChange={(e) => onCron(e.target.value || null)}
            />
          </Field>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label={`Most this campaign may spend a month (${currency})`}
          htmlFor="budget-month"
          hint="Leave empty for no cap of its own. AI work stays off until a cap is set in Settings."
        >
          <Input
            id="budget-month"
            type="number"
            inputMode="decimal"
            min={0}
            value={major(budget.monthly_cap_minor)}
            onChange={(e) =>
              onBudget({ ...budget, monthly_cap_minor: minor(e.target.value) })
            }
          />
        </Field>
        <Field
          label={`Most one run may spend (${currency})`}
          htmlFor="budget-run"
          hint="A run stops when it reaches this."
        >
          <Input
            id="budget-run"
            type="number"
            inputMode="decimal"
            min={0}
            value={major(budget.per_run_cap_minor)}
            onChange={(e) =>
              onBudget({ ...budget, per_run_cap_minor: minor(e.target.value) })
            }
          />
        </Field>
      </div>
    </>
  )
}
