import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { Sparkbar } from "@/components/sparkbar"
import {
  aiKeys,
  money,
  putSetting,
  settingQuery,
  spendQuery,
  stageLabel,
  type SpendSummary,
} from "./api"

type Field = {
  key: string
  label: string
  hint: string
  /** Shown in major units (dollars), stored in minor units (cents). */
  money?: boolean
}

const FIELDS: Field[] = [
  {
    key: "budget.monthly_cap_minor",
    label: "Monthly cap",
    hint: "Empty means paid AI work stays off.",
    money: true,
  },
  {
    key: "budget.per_run_cap_minor",
    label: "Per-run cap",
    hint: "Empty means no per-run cap.",
    money: true,
  },
  {
    key: "budget.warning_percent",
    label: "Warn at (%)",
    hint: "Share of the monthly cap that triggers one warning.",
  },
]

/** Monthly and per-run caps and the warning level (registry settings). */
export function BudgetSection() {
  return (
    <section aria-labelledby="ai-budget" className="grid gap-3">
      <SectionHeader
        title={<span id="ai-budget">Budget</span>}
        aside="Caps cover every paid call, including retries and route tests."
      />
      <div className="grid gap-3 sm:grid-cols-3">
        {FIELDS.map((f) => (
          <BudgetField key={f.key} field={f} />
        ))}
      </div>
    </section>
  )
}

function BudgetField({ field }: { field: Field }) {
  const queryClient = useQueryClient()
  const { data } = useQuery(settingQuery(field.key))
  const stored = data?.value as number | null | undefined
  const shown = (v: number | null | undefined) =>
    v == null ? "" : field.money ? String(v / 100) : String(v)
  // Local edit state, reset whenever the stored value changes (React's "adjust state on prop change").
  const [value, setValue] = useState("")
  const [seen, setSeen] = useState<number | null | undefined>(undefined)
  if (stored !== seen) {
    setSeen(stored)
    setValue(shown(stored))
  }
  const save = useMutation({
    mutationFn: () => {
      const n = value.trim() === "" ? null : Number(value)
      if (n !== null && (Number.isNaN(n) || n < 0))
        throw new Error("Enter a positive number.")
      return putSetting(
        field.key,
        n === null ? null : field.money ? Math.round(n * 100) : n
      )
    },
    onSuccess: () => {
      toast.success(`${field.label} saved.`)
      void queryClient.invalidateQueries({
        queryKey: aiKeys.setting(field.key),
      })
      void queryClient.invalidateQueries({ queryKey: aiKeys.spend })
    },
    onError: (e) => toast.error(e.message),
  })
  const id = `budget-${field.key}`
  return (
    <form
      className="grid content-start gap-1.5"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <Label htmlFor={id}>{field.label}</Label>
      <div className="flex gap-1.5">
        <Input
          id={id}
          inputMode="decimal"
          value={value}
          placeholder={field.money ? "Not set" : ""}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button
          type="submit"
          variant="outline"
          disabled={save.isPending || value === shown(stored)}
        >
          Save
        </Button>
      </div>
      <span className="text-xs text-faint">{field.hint}</span>
    </form>
  )
}

/** Spend so far this month: billed and estimated (not billed) kept apart, with a daily chart. */
export function SpendSection() {
  const { data } = useQuery(spendQuery())
  if (!data) return null
  return (
    <section aria-labelledby="ai-spend" className="grid gap-3">
      <SectionHeader
        title={<span id="ai-spend">Spend this month</span>}
        aside={`${data.month}, ${data.timezone}`}
        action={
          data.warning_reached ? (
            <Chip tone="warn">Past the warning level</Chip>
          ) : undefined
        }
      />
      <SpendTiles s={data} />
      {data.daily.length > 0 && (
        <Sparkbar
          values={data.daily.map((d) => d.billed_minor / 100)}
          edgeLabels={[
            data.daily[0].day.slice(5),
            data.daily[data.daily.length - 1].day.slice(5),
          ]}
          label={`Billed spend per day in ${data.currency}`}
          unit={data.currency}
          className="max-w-[420px]"
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Breakdown
          title="By stage"
          rows={data.by_stage}
          currency={data.currency}
          label={stageLabel}
        />
        <Breakdown
          title="By model"
          rows={data.by_model}
          currency={data.currency}
          label={(k) => k}
        />
      </div>
    </section>
  )
}

function SpendTiles({ s }: { s: SpendSummary }) {
  const tiles: [string, string, string?][] = [
    [
      "Billed",
      money(s.month_to_date_minor, s.currency),
      s.cap_minor ? `of ${money(s.cap_minor, s.currency)}` : "no cap set",
    ],
    ["Reserved now", money(s.reserved_minor, s.currency)],
    [
      "Remaining",
      s.remaining_minor == null ? "—" : money(s.remaining_minor, s.currency),
    ],
    [
      "Subscription (not billed)",
      money(s.estimated_unbilled_minor, s.currency),
      "estimated",
    ],
  ]
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {tiles.map(([label, value, sub]) => (
        <div key={label} className="grid gap-0.5 rounded-md bg-sunken p-2.5">
          <dt className="eyebrow">{label}</dt>
          <dd className="num text-lg font-semibold">{value}</dd>
          {sub && <dd className="text-xs text-faint">{sub}</dd>}
        </div>
      ))}
    </dl>
  )
}

function Breakdown({
  title,
  rows,
  currency,
  label,
}: {
  title: string
  rows: SpendSummary["by_stage"]
  currency: string
  label: (key: string) => string
}) {
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-faint">Nothing spent yet.</p>
      ) : (
        <ul className="grid gap-1 text-sm" aria-label={title}>
          {rows.map((r) => (
            <li key={r.key} className="flex justify-between gap-3">
              <span className="truncate">{label(r.key)}</span>
              <span className="num whitespace-nowrap text-muted-foreground">
                {money(r.billed_minor, currency)}
                {r.unbilled_minor > 0 &&
                  ` + ${money(r.unbilled_minor, currency)} est.`}
                {` · ${r.calls} calls`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
