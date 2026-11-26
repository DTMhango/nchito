import {
  Bell,
  FileText,
  Inbox,
  LayoutGrid,
  Search,
  Settings,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/chip"
import { ScoreRing } from "@/components/score-ring"
import { ThemeScope } from "@/themes/scope"
import { feColorMatrixValues, type Deficiency } from "@/themes/cvd"
import type { Mode, Theme } from "@/themes/schema"

/** Fictional rows for the preview table. Not data. */
const ROWS = [
  {
    score: 91,
    role: "Head of Data",
    org: "Example Payments",
    stage: "Interview",
    tone: "info" as const,
  },
  {
    score: 78,
    role: "Analytics Lead",
    org: "Sample Re",
    stage: "Applied",
    tone: "good" as const,
  },
  {
    score: 52,
    role: "Data Engineer",
    org: "Demo Logistics",
    stage: "Needs sign-in",
    tone: "warn" as const,
  },
  {
    score: 34,
    role: "BI Analyst",
    org: "Placeholder Bank",
    stage: "Closed",
    tone: "danger" as const,
  },
]
const BARS = [
  [4, 6, 3],
  [5, 7, 4],
  [3, 5, 6],
  [6, 8, 5],
  [7, 6, 7],
]

/**
 * The draft theme rendered with real components (shell, table, cards, buttons, chips, a form, a
 * chart, score rings, a document card). Everything sits in a ThemeScope, so the app's own root
 * tokens never change while editing. A colour-vision filter can be laid over the whole pane.
 */
export function StudioPreview({
  theme,
  mode,
  deficiency,
}: {
  theme: Theme
  mode: Mode
  deficiency: Deficiency | null
}) {
  const filterId = deficiency ? `cvd-${deficiency}` : undefined
  return (
    <div className="relative min-w-0">
      {deficiency && (
        <svg aria-hidden="true" className="absolute size-0" focusable="false">
          <filter id={`cvd-${deficiency}`}>
            <feColorMatrix
              type="matrix"
              values={feColorMatrixValues(deficiency)}
            />
          </filter>
        </svg>
      )}
      <ThemeScope
        theme={theme}
        mode={mode}
        data-testid="studio-preview"
        data-filter={filterId ?? "none"}
        role="region"
        aria-label={`Preview of ${theme.name}, ${mode}`}
        className="overflow-hidden rounded-lg border border-border text-[0.9rem]"
        style={filterId ? { filter: `url(#${filterId})` } : undefined}
      >
        <div className="grid min-h-[560px] grid-cols-[148px_minmax(0,1fr)] max-sm:grid-cols-1">
          <aside className="grid content-start gap-1 border-r border-border bg-sunken p-3 max-sm:hidden">
            <div className="mb-3 flex items-center gap-2 font-semibold">
              <span className="grid size-6 place-items-center rounded-sm bg-primary text-primary-foreground">
                <Sparkles className="size-3.5" aria-hidden="true" />
              </span>
              Nchito
            </div>
            {[
              { icon: LayoutGrid, label: "Today", active: true },
              { icon: Inbox, label: "Matches" },
              { icon: FileText, label: "Documents" },
              { icon: Settings, label: "Settings" },
            ].map(({ icon: Icon, label, active }) => (
              <span
                key={label}
                className={
                  active
                    ? "flex items-center gap-2 rounded-sm bg-primary-soft px-2 py-1.5 font-medium text-primary-ink"
                    : "flex items-center gap-2 rounded-sm px-2 py-1.5 text-muted-foreground"
                }
              >
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </span>
            ))}
          </aside>
          <div className="grid min-w-0 content-start gap-4 p-4">
            <header className="flex items-center gap-2">
              <span className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-surface px-2.5 text-faint">
                <Search className="size-3.5" aria-hidden="true" />
                Search or jump to
              </span>
              <Chip tone="good">Autopilot running</Chip>
              <Bell
                className="size-4 text-muted-foreground"
                aria-hidden="true"
              />
            </header>

            <div>
              <div className="eyebrow">Today</div>
              <h3 className="heading text-2xl">Needs you</h3>
              <p className="text-muted-foreground">
                Three approvals and one sign-in.{" "}
                <span className="text-faint">Updated 2 min ago</span>
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {[
                {
                  label: "Applied this week",
                  value: "12",
                  tone: "good" as const,
                  note: "+3",
                },
                {
                  label: "Replies",
                  value: "4",
                  tone: "info" as const,
                  note: "2 new",
                },
                {
                  label: "Spend",
                  value: "K 184",
                  tone: "warn" as const,
                  note: "61% of cap",
                },
              ].map((s) => (
                <div
                  key={s.label}
                  className="elev panel rounded-md border border-border bg-surface p-3"
                >
                  <div className="text-[0.8rem] text-muted-foreground">
                    {s.label}
                  </div>
                  <div className="num text-xl font-semibold">{s.value}</div>
                  <Chip tone={s.tone} className="mt-1">
                    {s.note}
                  </Chip>
                </div>
              ))}
            </div>

            <div className="overflow-hidden rounded-md border border-border bg-surface">
              <table className="w-full text-left">
                <thead className="bg-surface-2 text-[0.78rem] text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">Score</th>
                    <th className="px-3 py-2 font-medium">Role</th>
                    <th className="px-3 py-2 font-medium">Stage</th>
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map((r) => (
                    <tr key={r.role} className="border-t border-border">
                      <td className="px-3 row-pad">
                        <ScoreRing score={r.score} size={28} />
                      </td>
                      <td className="px-3 row-pad">
                        <div className="font-medium">{r.role}</div>
                        <div className="text-[0.8rem] text-muted-foreground">
                          {r.org}
                        </div>
                      </td>
                      <td className="px-3 row-pad">
                        <Chip tone={r.tone}>{r.stage}</Chip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <form
                className="grid gap-2.5 rounded-md border border-border bg-surface p-3"
                onSubmit={(e) => e.preventDefault()}
                aria-label="Sample form"
              >
                <div className="grid gap-1">
                  <Label htmlFor="pv-title">Job title</Label>
                  <Input id="pv-title" defaultValue="Head of Data" />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="pv-pay">Pay floor</Label>
                  <Input id="pv-pay" aria-invalid="true" defaultValue="abc" />
                  <span className="text-[0.8rem] text-danger">
                    Enter an amount.
                  </span>
                </div>
                <label className="flex items-center gap-2 text-[0.88rem]">
                  <Checkbox defaultChecked /> Ask before applying
                </label>
                <label className="flex items-center gap-2 text-[0.88rem]">
                  <Switch defaultChecked /> Remote only
                </label>
                <div className="flex flex-wrap gap-1.5">
                  <Button size="sm" type="button">
                    Approve
                  </Button>
                  <Button size="sm" variant="outline" type="button">
                    Edit
                  </Button>
                  <Button size="sm" variant="ghost" type="button">
                    Skip
                  </Button>
                  <Button size="sm" variant="destructive" type="button">
                    Withdraw
                  </Button>
                </div>
              </form>

              <div className="grid gap-3">
                <figure className="rounded-md border border-border bg-surface p-3">
                  <figcaption className="mb-2 text-[0.8rem] text-muted-foreground">
                    Applications by week
                  </figcaption>
                  <svg
                    viewBox="0 0 200 80"
                    className="h-24 w-full"
                    role="img"
                    aria-label="Sample bar chart"
                  >
                    {BARS.map((group, gi) =>
                      group.map((v, si) => (
                        <rect
                          key={`${gi}-${si}`}
                          x={8 + gi * 38 + si * 10}
                          y={76 - v * 8}
                          width={8}
                          height={v * 8}
                          rx={1.5}
                          style={{
                            fill: `var(--t-chart-${((gi + si) % 5) + 1})`,
                          }}
                        />
                      ))
                    )}
                    <line
                      x1="0"
                      x2="200"
                      y1="76.5"
                      y2="76.5"
                      style={{ stroke: "var(--t-border)" }}
                    />
                  </svg>
                  <div className="mt-1 flex flex-wrap gap-2 text-[0.75rem] text-muted-foreground">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <span key={n} className="flex items-center gap-1">
                        <i
                          className="block size-2 rounded-full"
                          style={{ background: `var(--t-chart-${n})` }}
                        />
                        Series {n}
                      </span>
                    ))}
                  </div>
                </figure>
                <article className="flex gap-3 rounded-md border border-border bg-surface-2 p-3">
                  <span className="grid h-14 w-11 shrink-0 place-items-center rounded-sm border border-border bg-surface text-primary-ink">
                    <FileText className="size-5" aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate font-semibold">
                      CV, Head of Data
                    </div>
                    <div className="text-[0.8rem] text-muted-foreground">
                      2 pages · tailored · checks passed
                    </div>
                    <div className="mt-1.5 flex gap-1.5">
                      <Chip tone="primary">Approved</Chip>
                      <Chip tone="accent">New</Chip>
                      <Chip tone="line">PDF</Chip>
                    </div>
                  </div>
                </article>
              </div>
            </div>
          </div>
        </div>
      </ThemeScope>
    </div>
  )
}
