import type { ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatCost } from "@/lib/cost"
import type { RunKind } from "@/features/sources/api"
import { KIND_LABEL } from "@/features/sources/words"
import type {
  CampaignFunnel,
  CountRow,
  InsightsFilters,
  InsightsReport,
  RateRow,
  SourceRow,
} from "./api"
import {
  days,
  downloadCsv,
  drill,
  pct,
  rowFilter,
  stageLabel,
  toCsv,
  type Drill,
} from "./lib"

const FUNNEL_LIST: Record<string, "matches" | "applications"> = {
  found: "matches",
  passed_filters: "matches",
  scored_above: "matches",
}

/** A number that opens the list it counts. */
export function Num({ to, children }: { to: Drill; children: ReactNode }) {
  return (
    <Link
      to={to.to}
      search={to.search as never}
      className="tabular-nums underline decoration-border-strong underline-offset-2 hover:text-primary"
    >
      {children}
    </Link>
  )
}

export function ExportButton({
  name,
  headers,
  rows,
}: {
  name: string
  headers: string[]
  rows: (string | number | null | undefined)[][]
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label={`Export ${name.replace(/-/g, " ")} as CSV`}
      onClick={() => downloadCsv(name, toCsv(headers, rows))}
    >
      <Download aria-hidden="true" /> CSV
    </Button>
  )
}

/** A thin bar, anchored to the left with a rounded data end. Decorative: the figures are in the table. */
function Bar({ ratio }: { ratio: number }) {
  return (
    <span
      aria-hidden="true"
      className="block h-2 w-full overflow-hidden rounded-full bg-sunken"
    >
      <span
        className="block h-full rounded-r-[4px] bg-primary"
        style={{ width: `${Math.max(2, Math.min(100, ratio * 100))}%` }}
      />
    </span>
  )
}

function Small({ children }: { children: ReactNode }) {
  return <p className="mt-2 text-sm text-muted-foreground">{children}</p>
}

const num = "text-right tabular-nums"

// ---- funnel --------------------------------------------------------------------------------

export function FunnelSection({
  funnel,
  filters,
}: {
  funnel: CampaignFunnel[]
  filters: InsightsFilters
}) {
  const rows = funnel.flatMap((c) =>
    c.steps.map((s) => [
      c.campaign,
      s.label,
      s.count,
      s.of_previous,
      s.of_found,
    ])
  )
  return (
    <section aria-labelledby="ins-funnel">
      <SectionHeader
        title={<span id="ins-funnel">Funnel by campaign</span>}
        aside="Found to offer, each role counted once"
        action={
          <ExportButton
            name="funnel"
            headers={["campaign", "step", "count", "of_previous", "of_found"]}
            rows={rows}
          />
        }
      />
      {funnel.length === 0 ? (
        <Small>
          No roles found in this range yet, so there is no funnel to show.
        </Small>
      ) : (
        funnel.map((c) => {
          const top = Math.max(1, c.steps[0]?.count ?? 1)
          const campaignFilter = c.campaign_id
            ? { campaign_id: c.campaign_id }
            : {}
          return (
            <div key={c.campaign_id ?? "none"} className="mb-5">
              <h3 className="mb-1 text-base font-semibold">{c.campaign}</h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Step</TableHead>
                    <TableHead className={num}>Roles</TableHead>
                    <TableHead className="w-[32%] max-md:hidden">
                      <span className="sr-only">Share of found</span>
                    </TableHead>
                    <TableHead className={num}>Of previous</TableHead>
                    <TableHead className={num}>Of found</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {c.steps.map((s) => (
                    <TableRow key={s.key}>
                      <TableCell>{s.label}</TableCell>
                      <TableCell className={num}>
                        <Num
                          to={drill(
                            { ...filters, ...campaignFilter },
                            { reached: s.key },
                            FUNNEL_LIST[s.key] ?? "applications"
                          )}
                        >
                          {s.count}
                        </Num>
                      </TableCell>
                      <TableCell className="max-md:hidden">
                        <Bar ratio={s.count / top} />
                      </TableCell>
                      <TableCell className={num}>
                        {pct(s.of_previous)}
                      </TableCell>
                      <TableCell className={num}>{pct(s.of_found)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )
        })
      )}
    </section>
  )
}

// ---- response rates ------------------------------------------------------------------------

function RateTable({
  title,
  dim,
  rows,
  filters,
}: {
  title: string
  dim: "track" | "source" | "market"
  rows: RateRow[]
  filters: InsightsFilters
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">{title}</h3>
        <ExportButton
          name={`response-by-${dim}`}
          headers={[dim, "sent", "replies", "interviews", "rate", "too_few"]}
          rows={rows.map((r) => [
            r.label,
            r.sent,
            r.replies,
            r.interviews,
            r.rate,
            r.too_few ? "yes" : "no",
          ])}
        />
      </div>
      {rows.length === 0 ? (
        <Small>Nothing sent in this range yet.</Small>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{title.replace("By ", "")}</TableHead>
              <TableHead className={num}>Sent</TableHead>
              <TableHead className={num}>Replies</TableHead>
              <TableHead className={num}>Reply rate</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const f = rowFilter(dim, r)
              return (
                <TableRow key={r.key}>
                  <TableCell>{r.label}</TableCell>
                  <TableCell className={num}>
                    <Num to={drill(filters, { ...f, reached: "sent" })}>
                      {r.sent}
                    </Num>
                  </TableCell>
                  <TableCell className={num}>
                    <Num to={drill(filters, { ...f, reached: "reply" })}>
                      {r.replies}
                    </Num>
                  </TableCell>
                  <TableCell className={num}>
                    {r.too_few ? (
                      <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                        <span className="text-muted-foreground">
                          {r.replies} of {r.sent}
                        </span>
                        <Chip tone="warn">Too few to tell</Chip>
                      </span>
                    ) : (
                      pct(r.rate)
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

export function RatesSection({
  report,
  filters,
}: {
  report: InsightsReport
  filters: InsightsFilters
}) {
  const r = report.response
  return (
    <section aria-labelledby="ins-rates">
      <SectionHeader
        title={<span id="ins-rates">Reply rate</span>}
        aside={`A rate from fewer than ${r.min_sample} sent applications is marked too few to tell`}
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <RateTable
          title="By track"
          dim="track"
          rows={r.by_track}
          filters={filters}
        />
        <RateTable
          title="By source"
          dim="source"
          rows={r.by_source}
          filters={filters}
        />
        <RateTable
          title="By market"
          dim="market"
          rows={r.by_market}
          filters={filters}
        />
      </div>
    </section>
  )
}

// ---- time in stage -------------------------------------------------------------------------

export function TimeSection({ report }: { report: InsightsReport }) {
  const rows = [
    ...report.time_in_stage.stages,
    report.time_in_stage.first_reply,
  ]
  const max = Math.max(1, ...rows.map((r) => r.p75_days ?? 0))
  return (
    <section aria-labelledby="ins-time">
      <SectionHeader
        title={<span id="ins-time">Time in stage</span>}
        aside="Median, and the slowest quarter (75th percentile)"
        action={
          <ExportButton
            name="time-in-stage"
            headers={["stage", "n", "median_days", "p75_days", "too_few"]}
            rows={rows.map((r) => [
              stageLabel(r.stage),
              r.n,
              r.median_days,
              r.p75_days,
              r.too_few ? "yes" : "no",
            ])}
          />
        }
      />
      {rows.every((r) => r.n === 0) ? (
        <Small>
          Not enough data yet: stages need a few moves to have a typical time.
        </Small>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Stage</TableHead>
              <TableHead className={num}>Roles</TableHead>
              <TableHead className={num}>Median</TableHead>
              <TableHead className={num}>75th percentile</TableHead>
              <TableHead className="w-[28%] max-md:hidden">
                <span className="sr-only">Median against slowest</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows
              .filter((r) => r.n > 0)
              .map((r) => (
                <TableRow key={r.stage}>
                  <TableCell>
                    {stageLabel(r.stage)}
                    {r.too_few && (
                      <Chip tone="warn" className="ml-2">
                        Too few to tell
                      </Chip>
                    )}
                  </TableCell>
                  <TableCell className={num}>{r.n}</TableCell>
                  <TableCell className={num}>{days(r.median_days)}</TableCell>
                  <TableCell className={num}>{days(r.p75_days)}</TableCell>
                  <TableCell className="max-md:hidden">
                    <Bar ratio={(r.median_days ?? 0) / max} />
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>
      )}
    </section>
  )
}

// ---- spend ---------------------------------------------------------------------------------

export function SpendSection({ report }: { report: InsightsReport }) {
  const s = report.spend
  const money = (m: number | null | undefined) =>
    m === null || m === undefined
      ? "-"
      : formatCost(m, { currency: s.currency })
  const periods = Object.entries(
    s.rows.reduce<Record<string, number>>((acc, r) => {
      acc[r.period] = (acc[r.period] ?? 0) + r.micros
      return acc
    }, {})
  ).sort(([a], [b]) => a.localeCompare(b))
  const peak = Math.max(1, ...periods.map(([, v]) => v))
  const byKey = (pick: (r: (typeof s.rows)[number]) => string) =>
    Object.entries(
      s.rows.reduce<Record<string, number>>((acc, r) => {
        acc[pick(r)] = (acc[pick(r)] ?? 0) + r.micros
        return acc
      }, {})
    ).sort(([, a], [, b]) => b - a)
  const byStage = byKey((r) => r.stage)
  const byModel = byKey((r) => r.model)

  return (
    <section aria-labelledby="ins-spend">
      <SectionHeader
        title={<span id="ins-spend">Spend</span>}
        aside={`AI cost from the ledger, per ${s.period}`}
        action={
          <ExportButton
            name="spend"
            headers={["period", "stage", "model", "micros"]}
            rows={s.rows.map((r) => [r.period, r.stage, r.model, r.micros])}
          />
        }
      />
      {s.rows.length === 0 ? (
        <Small>No AI spend recorded in this range.</Small>
      ) : (
        <>
          <dl className="mb-4 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
            <Stat label="Total" value={money(s.total_micros)} />
            <Stat
              label={`Per application sent (${s.sent})`}
              value={money(s.per_sent_micros)}
            />
            <Stat
              label={`Per interview (${s.interviews})`}
              value={money(s.per_interview_micros)}
            />
          </dl>
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="min-w-0">
              <h3 className="mb-1 text-base font-semibold">By {s.period}</h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Starting</TableHead>
                    <TableHead className={num}>Spend</TableHead>
                    <TableHead className="w-[45%] max-md:hidden">
                      <span className="sr-only">
                        Against the busiest period
                      </span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {periods.map(([p, v]) => (
                    <TableRow key={p}>
                      <TableCell>{p}</TableCell>
                      <TableCell className={num}>{money(v)}</TableCell>
                      <TableCell className="max-md:hidden">
                        <Bar ratio={v / peak} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="grid min-w-0 gap-4">
              <Breakdown title="By stage" rows={byStage} money={money} />
              <Breakdown title="By model" rows={byModel} money={money} />
              {s.by_run_kind.length > 0 && (
                <Breakdown
                  title="By kind of run"
                  rows={s.by_run_kind.map((r) => [
                    `${KIND_LABEL[r.kind as RunKind] ?? r.kind} (${r.runs} ${r.runs === 1 ? "run" : "runs"})`,
                    r.micros,
                  ])}
                  money={money}
                />
              )}
            </div>
          </div>
        </>
      )}
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  )
}

function Breakdown({
  title,
  rows,
  money,
}: {
  title: string
  rows: [string, number][]
  money: (m: number) => string
}) {
  return (
    <div>
      <h3 className="mb-1 text-base font-semibold">{title}</h3>
      <Table>
        <TableBody>
          {rows.map(([k, v]) => (
            <TableRow key={k}>
              <TableCell>{k}</TableCell>
              <TableCell className={num}>{money(v)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// ---- source quality ------------------------------------------------------------------------

export function SourcesSection({
  sources,
  filters,
}: {
  sources: SourceRow[]
  filters: InsightsFilters
}) {
  return (
    <section aria-labelledby="ins-sources">
      <SectionHeader
        title={<span id="ins-sources">Source quality</span>}
        aside="Roles each source found, and what became of them"
        action={
          <ExportButton
            name="source-quality"
            headers={[
              "source",
              "found",
              "duplicates",
              "passed",
              "applied",
              "replies",
            ]}
            rows={sources.map((r) => [
              r.name,
              r.found,
              r.duplicates,
              r.passed,
              r.applied,
              r.replies,
            ])}
          />
        }
      />
      {sources.length === 0 ? (
        <Small>No roles found in this range yet.</Small>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Source</TableHead>
              <TableHead className={num}>Found</TableHead>
              <TableHead className={num}>Duplicates</TableHead>
              <TableHead className={num}>Passed filters</TableHead>
              <TableHead className={num}>Applied</TableHead>
              <TableHead className={num}>Replies</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sources.map((r) => {
              const f = r.source_id ? { source_id: r.source_id } : {}
              return (
                <TableRow key={r.source_id ?? "none"}>
                  <TableCell>{r.name}</TableCell>
                  <TableCell className={num}>
                    <Num to={drill({ ...filters, ...f }, {}, "matches")}>
                      {r.found}
                    </Num>
                  </TableCell>
                  <TableCell className={num}>{r.duplicates}</TableCell>
                  <TableCell className={num}>{r.passed}</TableCell>
                  <TableCell className={num}>
                    <Num to={drill(filters, { ...f, reached: "sent" })}>
                      {r.applied}
                    </Num>
                  </TableCell>
                  <TableCell className={num}>
                    <Num to={drill(filters, { ...f, reached: "reply" })}>
                      {r.replies}
                    </Num>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </section>
  )
}

// ---- automation and exclusions -------------------------------------------------------------

function CountTable({
  title,
  rows,
  empty,
  name,
}: {
  title: string
  rows: CountRow[]
  empty: string
  name: string
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold">{title}</h3>
        <ExportButton
          name={name}
          headers={["item", "count"]}
          rows={rows.map((r) => [r.key, r.count])}
        />
      </div>
      {rows.length === 0 ? (
        <Small>{empty}</Small>
      ) : (
        <Table>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.key}>
                <TableCell className="whitespace-normal">
                  {r.key.replace(/_/g, " ")}
                </TableCell>
                <TableCell className={num}>{r.count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

const MESSAGE_KIND: Record<string, string> = {
  follow_up: "follow-up",
  thank_you: "thank-you",
  info_reply: "reply with information",
  slot_accept: "slot accepted",
  slot_decline: "slot declined",
  withdraw: "withdrawal",
  offer_decline: "offer declined",
}

/** Messages about applications, counted apart: they never add to the applications above. */
function MessagesLine({ messages }: { messages: InsightsReport["messages"] }) {
  const kinds = messages.by_kind
    .map((r) => `${r.count} ${MESSAGE_KIND[r.key] ?? r.key.replace(/_/g, " ")}`)
    .join(", ")
  return (
    <p
      data-testid="insights-messages"
      className="text-sm text-muted-foreground"
    >
      Messages about applications (not counted as applications):{" "}
      <b className="num text-foreground">{messages.sent}</b> sent
      {kinds ? ` (${kinds})` : ""}
      {messages.uncertain_sends > 0
        ? `, ${messages.uncertain_sends} not confirmed yet`
        : ""}
      .
    </p>
  )
}

export function AutomationSection({ report }: { report: InsightsReport }) {
  const a = report.automation
  const sent = a.auto + a.approved + a.manual
  return (
    <section aria-labelledby="ins-auto">
      <SectionHeader
        title={<span id="ins-auto">Automation and exclusions</span>}
        aside="How applications went out, what stopped the runner, what filtered roles out"
      />
      <dl className="mb-4 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
        <Stat label="Sent automatically" value={String(a.auto)} />
        <Stat label="Sent after your approval" value={String(a.approved)} />
        <Stat label="Applied by hand" value={String(a.manual)} />
        <Stat label="Uncertain sends" value={String(a.uncertain_sends)} />
      </dl>
      {sent === 0 && (
        <Small>
          Nothing sent in this range yet, so there is no split to show.
        </Small>
      )}
      <MessagesLine messages={report.messages} />
      <div className="mt-3 grid gap-6 lg:grid-cols-3">
        <CountTable
          title="Blockers by kind"
          name="blockers"
          rows={a.blockers}
          empty="No blockers raised."
        />
        <CountTable
          title="Permits denied, by reason"
          name="permits-denied"
          rows={a.permits_denied}
          empty="No permits denied."
        />
        <CountTable
          title="What excluded roles most"
          name="exclusions"
          rows={report.exclusions}
          empty="No roles excluded by a hard filter."
        />
      </div>
    </section>
  )
}
