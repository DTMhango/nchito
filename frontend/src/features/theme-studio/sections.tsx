import { useId, useState, type Dispatch, type SetStateAction } from "react"
import { Minus, Plus, Wand2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Segmented } from "@/components/segmented"
import { Slider } from "@/components/ui/slider"
import { asHex6, derivePalette, PICKER_PLACEHOLDER } from "@/themes/derive"
import { FONT_FAMILIES, TOKEN_SPEC, tokensInGroup } from "@/themes/spec"
import type { Mode } from "@/themes/schema"
import { isLiteralColour } from "@/themes/colour"
import type { ThemeBody } from "./api"
import { TokenField } from "./token-field"

type DraftProps = {
  draft: ThemeBody
  setDraft: Dispatch<SetStateAction<ThemeBody>>
  readOnly: boolean
}

const FONT_SLOTS = [
  { slot: "display", label: "Headings" },
  { slot: "body", label: "Body" },
  { slot: "mono", label: "Monospace" },
] as const

function Row({
  label,
  htmlFor,
  children,
  error,
}: {
  label: string
  htmlFor?: string
  children: React.ReactNode
  error?: string
}) {
  return (
    <div className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 py-1.5">
      <label htmlFor={htmlFor} className="text-[0.86rem] font-medium">
        {label}
      </label>
      <div className="min-w-0">{children}</div>
      {error && (
        <span role="alert" className="col-start-2 text-[0.76rem] text-danger">
          {error}
        </span>
      )}
    </div>
  )
}

const inputClass =
  "field-focus h-8 w-full min-w-0 rounded-md border border-border bg-surface px-2 text-[0.88rem] disabled:opacity-60"

/** Name, description, fonts (bundled families only), radius and density. */
export function BasicsSection({
  draft,
  setDraft,
  readOnly,
  issueAt,
}: DraftProps & { issueAt: (p: string) => string | undefined }) {
  const id = useId()
  return (
    <div className="divide-y divide-border">
      <Row label="Name" htmlFor={`${id}-name`} error={issueAt("name")}>
        <input
          id={`${id}-name`}
          className={inputClass}
          maxLength={80}
          disabled={readOnly}
          value={draft.name}
          onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
        />
      </Row>
      <Row label="Description" htmlFor={`${id}-desc`}>
        <input
          id={`${id}-desc`}
          className={inputClass}
          maxLength={200}
          disabled={readOnly}
          value={draft.description ?? ""}
          onChange={(e) =>
            setDraft((d) => ({ ...d, description: e.target.value || null }))
          }
        />
      </Row>
      {FONT_SLOTS.map(({ slot, label }) => (
        <Row
          key={slot}
          label={`${label} font`}
          htmlFor={`${id}-${slot}`}
          error={issueAt(`fonts.${slot}`)}
        >
          <select
            id={`${id}-${slot}`}
            className={inputClass}
            disabled={readOnly}
            value={draft.fonts[slot]}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                fonts: { ...d.fonts, [slot]: e.target.value },
              }))
            }
          >
            {FONT_FAMILIES.filter((f) =>
              slot === "mono" ? TOKEN_SPEC.fonts[f] === "mono" : true
            ).map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </Row>
      ))}
      <Row label="Corner radius">
        <div className="flex items-center gap-3">
          <Slider
            aria-label="Corner radius"
            className="min-w-0 flex-1"
            min={0}
            max={32}
            step={1}
            disabled={readOnly}
            value={[draft.radius]}
            onValueChange={([v]) => setDraft((d) => ({ ...d, radius: v }))}
          />
          <span className="w-10 text-right num text-[0.86rem]">
            {draft.radius}px
          </span>
        </div>
      </Row>
      <Row label="Density">
        <Segmented<ThemeBody["density"]>
          aria-label="Density"
          value={draft.density}
          onValueChange={(v) =>
            !readOnly && setDraft((d) => ({ ...d, density: v }))
          }
          options={[
            { value: "comfortable", label: "Comfortable" },
            { value: "compact", label: "Compact" },
          ]}
        />
      </Row>
    </div>
  )
}

/** Generate a whole palette from one or two seed colours, then hand-tune. */
export function GenerateSection({ draft, setDraft, readOnly }: DraftProps) {
  const id = useId()
  const [primary, setPrimary] = useState(
    () => asHex6(draft.light.primary) ?? PICKER_PLACEHOLDER
  )
  const [accent, setAccent] = useState<string>(
    () => asHex6(draft.light.accent) ?? ""
  )
  const [useAccent, setUseAccent] = useState(true)
  const valid =
    isLiteralColour(primary) &&
    (!useAccent || !accent || isLiteralColour(accent))

  const apply = () => {
    const p = derivePalette({
      primary,
      accent: useAccent && accent ? accent : null,
    })
    // Keep the theme's character tokens (shadows, type, spacing); replace every colour.
    setDraft((d) => ({
      ...d,
      light: { ...d.light, ...p.light },
      dark: { ...d.dark, ...p.dark },
      chart: p.chart,
      score: p.score,
    }))
  }

  const seed = (
    label: string,
    key: string,
    value: string,
    set: (v: string) => void
  ) => (
    <Row label={label} htmlFor={`${id}-${key}`}>
      <div className="flex items-center gap-2">
        <span
          className="relative size-8 shrink-0 overflow-hidden rounded-sm border border-border-strong"
          style={{ background: isLiteralColour(value) ? value : undefined }}
        >
          <input
            type="color"
            aria-label={`${label} picker`}
            value={asHex6(value) ?? PICKER_PLACEHOLDER}
            onChange={(e) => set(e.target.value.toUpperCase())}
            className="absolute inset-0 size-full cursor-pointer opacity-0"
          />
        </span>
        <input
          id={`${id}-${key}`}
          className={`${inputClass} font-mono`}
          value={value}
          spellCheck={false}
          onChange={(e) => set(e.target.value)}
          aria-invalid={value && !isLiteralColour(value) ? true : undefined}
        />
      </div>
    </Row>
  )

  return (
    <div className="grid gap-2">
      <p className="text-[0.86rem] text-muted-foreground">
        Pick one or two seed colours. Every surface, text, border, accent,
        status, chart and score colour is derived from them in OKLCH, for light
        and dark, with text pushed until it passes AA. Status colours keep their
        own hues (green, amber, red, blue). Shadows, type and spacing stay as
        they are.
      </p>
      {seed("Primary seed", "primary", primary, setPrimary)}
      <label className="flex items-center gap-2 text-[0.86rem]">
        <input
          type="checkbox"
          checked={useAccent}
          onChange={(e) => setUseAccent(e.target.checked)}
        />
        Use my own accent seed (otherwise one is derived)
      </label>
      {useAccent && seed("Accent seed", "accent", accent, setAccent)}
      <div>
        <Button size="sm" disabled={readOnly || !valid} onClick={apply}>
          <Wand2 aria-hidden="true" /> Generate palette
        </Button>
        {readOnly && (
          <span className="ml-2 text-[0.8rem] text-faint">
            Duplicate the theme to generate.
          </span>
        )}
      </div>
    </div>
  )
}

/** The chart palette (top-level, light fallback; 1 to 12) and the per-mode series and score ramp. */
export function ChartSection({
  draft,
  setDraft,
  readOnly,
  mode,
  setToken,
  issueAt,
}: DraftProps & {
  mode: Mode
  setToken: (mode: Mode, name: string, value: string | undefined) => void
  issueAt: (p: string) => string | undefined
}) {
  const max = TOKEN_SPEC.limits.chart_colours
  return (
    <div className="grid gap-3">
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[0.86rem] font-semibold">
            Palette (fallback for every mode)
          </span>
          <span className="flex gap-1">
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label="Remove last chart colour"
              disabled={readOnly || draft.chart.length <= 1}
              onClick={() =>
                setDraft((d) => ({ ...d, chart: d.chart.slice(0, -1) }))
              }
            >
              <Minus aria-hidden="true" />
            </Button>
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label="Add chart colour"
              disabled={readOnly || draft.chart.length >= max}
              onClick={() =>
                setDraft((d) => ({
                  ...d,
                  chart: [...d.chart, d.chart[d.chart.length - 1]],
                }))
              }
            >
              <Plus aria-hidden="true" />
            </Button>
          </span>
        </div>
        <div className="divide-y divide-border">
          {draft.chart.map((c, i) => (
            <TokenField
              key={`chart-${i}`}
              name={`chart-palette-${i + 1}`}
              spec={{ type: "colour", label: `Colour ${i + 1}` }}
              value={c}
              disabled={readOnly}
              issue={issueAt(`chart.${i}`)}
              onChange={(v) =>
                v &&
                setDraft((d) => ({
                  ...d,
                  chart: d.chart.map((x, j) => (j === i ? v : x)),
                }))
              }
            />
          ))}
          {(["low", "mid", "high"] as const).map((k) => (
            <TokenField
              key={`score-${k}`}
              name={`score-ramp-${k}`}
              spec={{ type: "colour", label: `Score ${k}` }}
              value={draft.score[k]}
              disabled={readOnly}
              issue={issueAt(`score.${k}`)}
              onChange={(v) =>
                v && setDraft((d) => ({ ...d, score: { ...d.score, [k]: v } }))
              }
            />
          ))}
        </div>
      </div>
      <div>
        <div className="mb-1 text-[0.86rem] font-semibold">
          {mode === "light" ? "Light" : "Dark"} overrides
        </div>
        <div className="divide-y divide-border">
          {tokensInGroup("chart").map((name) => (
            <TokenField
              key={`${mode}-${name}`}
              name={name}
              spec={TOKEN_SPEC.tokens[name]}
              value={draft[mode][name]}
              disabled={readOnly}
              issue={issueAt(`${mode}.${name}`)}
              onChange={(v) => setToken(mode, name, v)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
