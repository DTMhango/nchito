import { useId, useState } from "react"
import { asHex6, PICKER_PLACEHOLDER } from "@/themes/derive"
import type { TokenSpec } from "@/themes/spec"
import { validTokenValue } from "@/themes/validate"
import { cn } from "@/lib/utils"

const HINTS: Partial<Record<TokenSpec["type"], string>> = {
  colour: "hex, rgb, hsl, oklch or var(--t-token)",
  shadow: "none, or x y blur [spread] colour",
  weight: "100 to 900",
  track: "em, e.g. -0.01em",
  factor: "number",
  length: "px",
}

/**
 * One token: a swatch with the native picker, plus the exact value as text. The text is checked
 * against the same grammar the server enforces, and only a valid value reaches the draft.
 */
export function TokenField({
  name,
  spec,
  value,
  onChange,
  disabled,
  issue,
}: {
  name: string
  spec: Pick<TokenSpec, "type" | "label" | "values" | "min" | "max">
  value: string | undefined
  onChange: (value: string | undefined) => void
  disabled?: boolean
  issue?: string
}) {
  const id = useId()
  const [text, setText] = useState(value ?? "")
  // Follow outside changes (generate, a suggested fix, undo) without an effect.
  const [seen, setSeen] = useState(value)
  if (seen !== value) {
    setSeen(value)
    setText(value ?? "")
  }
  const valid = text === "" || validTokenValue(name, text)
  const hex = spec.type === "colour" ? asHex6(text) : null
  const error = !valid ? "Not an allowed value." : issue

  const commit = (v: string) => {
    setText(v)
    if (v === "") onChange(undefined)
    else if (validTokenValue(name, v)) onChange(v)
  }

  return (
    <div className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 py-1.5">
      <label htmlFor={id} className="min-w-0">
        <span className="block truncate text-[0.86rem] font-medium">
          {spec.label}
        </span>
        <span className="block truncate font-mono text-[0.72rem] text-faint">
          {name}
        </span>
      </label>
      <div className="flex min-w-0 items-center gap-2">
        {spec.type === "colour" && (
          <span
            className="relative size-7 shrink-0 overflow-hidden rounded-sm border border-border-strong"
            style={{ background: valid && text ? text : undefined }}
          >
            <input
              type="color"
              aria-label={`${spec.label} picker`}
              disabled={disabled || hex === null}
              value={hex ?? PICKER_PLACEHOLDER}
              onChange={(e) => commit(e.target.value.toUpperCase())}
              className="absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
            />
          </span>
        )}
        {spec.type === "enum" ? (
          <select
            id={id}
            aria-label={`${spec.label} (${name})`}
            disabled={disabled}
            value={text}
            onChange={(e) => commit(e.target.value)}
            className="h-8 min-w-0 flex-1 rounded-md border field-focus border-border bg-surface px-2 text-[0.86rem]"
          >
            <option value="">Theme engine default</option>
            {(spec.values ?? []).map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={id}
            aria-label={`${spec.label} (${name})`}
            disabled={disabled}
            value={text}
            spellCheck={false}
            autoComplete="off"
            placeholder={HINTS[spec.type]}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-err` : undefined}
            onChange={(e) => commit(e.target.value)}
            className={cn(
              "h-8 min-w-0 flex-1 rounded-md border field-focus border-border bg-surface px-2 font-mono text-[0.8rem] disabled:opacity-60",
              error && "border-danger"
            )}
          />
        )}
      </div>
      {error && (
        <span
          id={`${id}-err`}
          role="alert"
          className="col-start-2 text-[0.76rem] text-danger"
        >
          {error}
        </span>
      )}
    </div>
  )
}
