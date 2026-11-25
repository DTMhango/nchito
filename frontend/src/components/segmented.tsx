import type { ReactNode } from "react"
import type { LucideIcon } from "lucide-react"
import { RadioGroup as RadioGroupPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"

export type SegmentOption<T extends string> = {
  value: T
  label: ReactNode
  icon?: LucideIcon
  disabled?: boolean
}

type SegmentedProps<T extends string> = {
  value: T
  onValueChange: (value: T) => void
  options: SegmentOption<T>[]
  /** Required: what is being chosen ("Mode", "Density"). */
  "aria-label": string
  size?: "default" | "sm"
  className?: string
}

/**
 * Segmented control for 2 to 5 exclusive options (mode, density, layout, channel).
 * A radio group underneath: arrow keys move, the selection follows focus.
 */
export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  size = "default",
  className,
  ...rest
}: SegmentedProps<T>) {
  return (
    <RadioGroupPrimitive.Root
      value={value}
      onValueChange={(v) => onValueChange(v as T)}
      aria-label={rest["aria-label"]}
      orientation="horizontal"
      className={cn(
        "relative inline-flex w-fit gap-0.5 rounded-md border border-border bg-sunken p-0.5",
        className
      )}
    >
      {options.map((o) => (
        <RadioGroupPrimitive.Item
          key={o.value}
          value={o.value}
          disabled={o.disabled}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-[max(0px,calc(var(--t-radius-sm)-2px))] font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50",
            "focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-primary-ink",
            "data-[state=checked]:bg-surface data-[state=checked]:text-foreground data-[state=checked]:shadow-sm data-[state=checked]:outline-1 data-[state=checked]:outline-border",
            size === "default" ? "px-2.75 py-1 text-sm" : "px-2 py-0.5 text-xs",
            "[&_svg]:size-[15px]"
          )}
        >
          {o.icon && <o.icon aria-hidden="true" strokeWidth={1.75} />}
          {o.label}
        </RadioGroupPrimitive.Item>
      ))}
    </RadioGroupPrimitive.Root>
  )
}
