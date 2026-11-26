import { useMemo, useState } from "react"
import { AlertTriangle, Check, Wand2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { Segmented } from "@/components/segmented"
import { resolveColour, toHexAlpha } from "@/themes/colour"
import {
  evaluateContrast,
  suggestFix,
  tokenEnv,
  type PairResult,
} from "@/themes/contrast"
import { statusClashes } from "@/themes/cvd"
import { TOKEN_SPEC } from "@/themes/spec"
import type { Mode } from "@/themes/schema"
import type { ThemeBody } from "./api"

type Filter = "problems" | "all"

/** Every pair, both modes: failures first, then lowest ratio. */
export function contrastResults(t: ThemeBody): PairResult[] {
  const score = t.score as Record<string, string>
  return [
    ...evaluateContrast(t.light, "light", t.chart, score),
    ...evaluateContrast(t.dark, "dark", t.chart, score),
  ].sort(
    (a, b) =>
      Number(b.blocking) - Number(a.blocking) ||
      Number(a.aa) - Number(b.aa) ||
      a.ratio - b.ratio
  )
}

/** A token's resolved colour (following var() references) for an inline sample. */
function swatch(t: ThemeBody, mode: Mode, token: string): string | undefined {
  const env = tokenEnv(t[mode], t.chart, t.score as Record<string, string>)
  try {
    return toHexAlpha(resolveColour(env[token], env))
  } catch {
    return undefined
  }
}

const label = (token: string) => TOKEN_SPEC.tokens[token]?.label ?? token

/**
 * WCAG contrast for every text/surface pair the app uses (derived from the token spec), with
 * AA/AAA per pair, a one-click nearest passing colour, and the status-colour separation check.
 */
export function ContrastPanel({
  draft,
  results,
  minStatusDistance,
  onFix,
  readOnly,
}: {
  draft: ThemeBody
  results: PairResult[]
  minStatusDistance: number | null
  onFix: (mode: Mode, token: string, value: string) => void
  readOnly: boolean
}) {
  const [filter, setFilter] = useState<Filter>("problems")
  const failing = results.filter((r) => !r.aa)
  const shown = filter === "problems" ? failing : results
  const clashes = useMemo(
    () =>
      minStatusDistance === null
        ? null
        : (["light", "dark"] as const).flatMap((m) =>
            statusClashes(draft[m], minStatusDistance).map((c) => ({
              ...c,
              mode: m,
            }))
          ),
    [draft, minStatusDistance]
  )

  return (
    <section aria-labelledby="contrast-title" className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="contrast-title" className="font-semibold">
          Contrast{" "}
          <span className="text-[0.82rem] font-normal text-muted-foreground">
            {results.length - failing.length} of {results.length} pairs pass AA
          </span>
        </h3>
        <Segmented<Filter>
          aria-label="Show pairs"
          value={filter}
          onValueChange={setFilter}
          options={[
            { value: "problems", label: `Problems (${failing.length})` },
            { value: "all", label: "All" },
          ]}
        />
      </div>

      {shown.length === 0 ? (
        <p className="flex items-center gap-2 text-[0.88rem] text-good">
          <Check className="size-4" aria-hidden="true" /> Every pair passes AA.
        </p>
      ) : (
        <ul
          aria-label="Contrast pairs"
          className="grid max-h-[340px] gap-px overflow-y-auto rounded-md border border-border bg-border"
        >
          {shown.map((r) => (
            <PairRow
              key={`${r.mode}-${r.fg}-${r.bg}`}
              r={r}
              draft={draft}
              onFix={onFix}
              readOnly={readOnly}
            />
          ))}
        </ul>
      )}

      <div className="rounded-md border border-border bg-surface p-3 text-[0.86rem]">
        <div className="mb-1 font-semibold">
          Status colours under colour-blindness
        </div>
        {clashes === null ? (
          <p className="text-muted-foreground">
            Couldn't load the separation setting, so this check is off.
          </p>
        ) : clashes.length === 0 ? (
          <p className="flex items-center gap-2 text-good">
            <Check className="size-4" aria-hidden="true" /> Good, warning,
            danger and info stay distinct in normal vision, protanopia,
            deuteranopia and tritanopia.
          </p>
        ) : (
          <ul
            role="list"
            aria-label="Status colour clashes"
            className="grid gap-1"
          >
            {clashes.map((c) => (
              <li
                key={`${c.mode}-${c.deficiency}-${c.a}-${c.b}`}
                className="flex items-start gap-2 text-warn"
              >
                <AlertTriangle
                  className="mt-0.5 size-4 shrink-0"
                  aria-hidden="true"
                />
                <span>
                  {label(c.a)} and {label(c.b)} look alike in {c.mode} mode
                  {c.deficiency ? ` with ${c.deficiency}` : ""} (distance{" "}
                  {c.distance}, needs {minStatusDistance}).
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

function PairRow({
  r,
  draft,
  onFix,
  readOnly,
}: {
  r: PairResult
  draft: ThemeBody
  onFix: (mode: Mode, token: string, value: string) => void
  readOnly: boolean
}) {
  const fix = useMemo(
    () =>
      r.aa
        ? null
        : suggestFix(
            draft[r.mode],
            r.mode,
            r,
            draft.chart,
            draft.score as Record<string, string>
          ),
    [r, draft]
  )
  const lvl = TOKEN_SPEC.levels[r.use]
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 bg-surface px-3 py-2">
      <span
        aria-hidden="true"
        className="grid h-8 w-10 place-items-center rounded-sm border border-border text-[0.8rem] font-semibold"
        style={{
          background: swatch(draft, r.mode, r.bg),
          color: swatch(draft, r.mode, r.fg),
        }}
      >
        Aa
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[0.86rem]">
          {label(r.fg)} on {label(r.bg)}
        </span>
        <span className="block text-[0.75rem] text-faint">
          {r.mode} · {lvl.label}
          {r.blocking && (
            <b className="ml-1 font-semibold text-danger">blocks saving</b>
          )}
        </span>
      </span>
      <span className="flex items-center gap-1.5">
        <span className="num text-[0.86rem]">{r.ratio.toFixed(2)}</span>
        <Chip tone={r.aa ? "good" : r.blocking ? "danger" : "warn"}>
          {r.aa ? "AA" : "Fails AA"}
        </Chip>
        {r.aaa !== null && r.aa && (
          <Chip tone={r.aaa ? "good" : "neutral"}>
            {r.aaa ? "AAA" : "no AAA"}
          </Chip>
        )}
        {fix && !readOnly && (
          <Button
            size="xs"
            variant="outline"
            onClick={() => onFix(r.mode, r.fg, fix)}
            aria-label={`Use ${fix} for ${label(r.fg)} in ${r.mode} mode`}
          >
            <Wand2 aria-hidden="true" />
            {fix}
          </Button>
        )}
      </span>
    </li>
  )
}
