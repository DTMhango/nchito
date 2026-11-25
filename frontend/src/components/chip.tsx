import type { ComponentProps, KeyboardEvent } from "react"
import { Check, Minus, type LucideIcon } from "lucide-react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

export const chipVariants = cva(
  "inline-flex items-center gap-[5px] rounded-full border border-transparent px-2 py-0.5 text-[0.78rem] leading-[1.35] font-medium whitespace-nowrap [&_svg]:size-[13px] [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "bg-sunken text-muted-foreground",
        good: "bg-good-soft text-good",
        warn: "bg-warn-soft text-warn",
        danger: "bg-danger-soft text-danger",
        info: "bg-info-soft text-info",
        accent: "bg-highlight-soft text-highlight-ink",
        primary: "bg-primary-soft text-primary-ink",
        line: "border-border bg-transparent text-muted-foreground",
      },
    },
    defaultVariants: { tone: "neutral" },
  }
)

export type ChipTone = NonNullable<VariantProps<typeof chipVariants>["tone"]>

type ChipProps = ComponentProps<"span"> &
  VariantProps<typeof chipVariants> & { icon?: LucideIcon }

/** A compact status or attribute label. Tones are semantic, never the theme accent by accident. */
export function Chip({
  tone,
  icon: Icon,
  className,
  children,
  ...props
}: ChipProps) {
  return (
    <span
      data-slot="chip"
      className={cn(chipVariants({ tone }), className)}
      {...props}
    >
      {Icon && <Icon aria-hidden="true" />}
      {children}
    </span>
  )
}

/** A small count badge (nav items, section headers). */
export function CountBadge({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "rounded-full bg-highlight-soft px-[7px] py-px num text-[0.72rem] font-semibold text-highlight-ink",
        className
      )}
      {...props}
    />
  )
}

// ---------------------------------------------------------------------------
// Three-state filter chip (DESIGN 6.1): each facet value cycles include -> exclude -> off.
// ---------------------------------------------------------------------------

export type FilterState = "include" | "exclude" | "off"

export function nextFilterState(s: FilterState): FilterState {
  if (s === "off") return "include"
  if (s === "include") return "exclude"
  return "off"
}

const STATE_TEXT: Record<FilterState, string> = {
  include: "included",
  exclude: "excluded",
  off: "not filtering",
}

type FilterChipProps = Omit<ComponentProps<"button">, "onChange" | "value"> & {
  /** Facet value label, e.g. "Not stated" or "Sponsorship offered". */
  label: string
  /** Facet name, read before the value by screen readers, e.g. "Visa sponsorship". */
  facet?: string
  state: FilterState
  onStateChange: (next: FilterState) => void
  /** Jobs matching this value, shown after the label. */
  count?: number
}

/**
 * Click or press Enter/Space to cycle include, exclude, off. Delete or Backspace clears.
 * "Not stated" is a value like any other and can be included or excluded.
 */
export function FilterChip({
  label,
  facet,
  state,
  onStateChange,
  count,
  className,
  onKeyDown,
  ...props
}: FilterChipProps) {
  const handleKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    onKeyDown?.(e)
    if (e.defaultPrevented) return
    if ((e.key === "Delete" || e.key === "Backspace") && state !== "off") {
      e.preventDefault()
      onStateChange("off")
    }
  }
  const next = nextFilterState(state)
  return (
    <button
      type="button"
      data-slot="filter-chip"
      data-state={state}
      onClick={() => onStateChange(next)}
      onKeyDown={handleKey}
      title={`Click to ${next === "off" ? "clear" : next}`}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-sm font-medium whitespace-nowrap transition-colors [&_svg]:size-[13px]",
        state === "off" &&
          "border-border bg-surface text-muted-foreground hover:border-border-strong hover:text-foreground",
        state === "include" &&
          "border-primary bg-primary-soft text-primary-ink",
        state === "exclude" && "border-danger bg-danger-soft text-danger",
        className
      )}
      {...props}
    >
      {state === "include" && <Check aria-hidden="true" />}
      {state === "exclude" && <Minus aria-hidden="true" />}
      <span className={cn(state === "exclude" && "line-through decoration-1")}>
        {label}
      </span>
      {count !== undefined && (
        <span className="num text-xs opacity-75">{count}</span>
      )}
      <span className="sr-only">
        {facet ? `${facet}: ` : ""}
        {STATE_TEXT[state]}
      </span>
    </button>
  )
}
