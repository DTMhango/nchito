import type { PolicyPreviewOut } from "./api"

type Bin = PolicyPreviewOut["histogram"][number]

const binLabel = (b: Bin) => `${b.start} to ${Math.max(b.start, b.end - 1)}`
const roles = (n: number) => `${n} ${n === 1 ? "role" : "roles"}`

/**
 * Scores of recent roles in bins over a 0-100 axis, one series (chart-1). Bars at or above the
 * auto-apply line are full strength; the rest recede. Vertical rules mark the three lines.
 * Each bar has a hover title; a table carries the same numbers for screen readers and print.
 */
export function ScoreHistogram({
  bins,
  shortlist,
  tailor,
  auto,
  unscored,
}: {
  bins: Bin[]
  shortlist: number
  tailor: number
  auto: number
  unscored: number
}) {
  const max = Math.max(1, ...bins.map((b) => b.count))
  const total = bins.reduce((s, b) => s + b.count, 0)
  const atOrAbove = bins
    .filter((b) => b.start >= auto)
    .reduce((s, b) => s + b.count, 0)
  return (
    <div className="grid gap-1">
      <div
        role="img"
        aria-label={`Scores of ${roles(total)} in ${bins.length} bars; about ${atOrAbove} at or above the auto-apply line ${auto}.`}
        className="relative h-[96px]"
      >
        <div className="absolute inset-0 flex items-end gap-[2px] border-b border-border">
          {bins.map((b) => (
            <div
              key={b.start}
              className="flex h-full flex-1 items-end justify-center"
              title={`${binLabel(b)}: ${roles(b.count)}`}
            >
              <div
                className={
                  "w-full max-w-6 rounded-t-[4px] bg-chart-1 " +
                  (b.start >= auto ? "" : "opacity-40")
                }
                style={{ height: `${(b.count / max) * 100}%` }}
              />
            </div>
          ))}
        </div>
        <Marker at={shortlist} className="bg-border-strong" />
        <Marker at={tailor} className="bg-muted-foreground" />
        <Marker at={auto} className="bg-foreground" />
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-muted-foreground">
          Show the scores as a table
          {unscored > 0 ? ` (${roles(unscored)} not scored)` : ""}
        </summary>
        <table className="mt-1 text-xs">
          <caption className="sr-only">Roles per score band</caption>
          <thead>
            <tr>
              <th className="pr-4 text-left font-medium">Score</th>
              <th className="text-right font-medium">Roles</th>
            </tr>
          </thead>
          <tbody>
            {bins.map((b) => (
              <tr key={b.start}>
                <td className="pr-4">{binLabel(b)}</td>
                <td className="text-right num">{b.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}

function Marker({ at, className }: { at: number; className: string }) {
  return (
    <span
      aria-hidden="true"
      className={"absolute inset-y-0 w-px " + className}
      style={{ left: `${at}%` }}
    />
  )
}
