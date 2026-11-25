import type { ComponentProps, ReactNode } from "react"
import { Check, CircleAlert, Loader2 } from "lucide-react"
import { Chip } from "@/components/chip"
import { cn } from "@/lib/utils"
import type { SaveState } from "./use-autosave"

/** A native select styled like Input: reliable on phones and with keyboards. */
export function NativeSelect({
  className,
  ...props
}: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-8 w-full min-w-0 rounded-md border field-focus border-input bg-surface px-2 text-base text-foreground outline-none disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

/** A titled block in the editor. `id` is the anchor the section nav jumps to. */
export function EditorSection({
  id,
  number,
  title,
  lead,
  children,
}: {
  id: string
  number: number
  title: string
  lead: ReactNode
  children: ReactNode
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-h`}
      className="scroll-mt-24 border-t border-border pt-5 pb-7"
    >
      <h3 id={`${id}-h`} className="flex items-baseline gap-2 text-lg">
        <span className="num text-sm text-faint">{number}</span>
        {title}
      </h3>
      <p className="mt-1 mb-4 max-w-[68ch] text-muted-foreground">{lead}</p>
      <div className="grid gap-5">{children}</div>
    </section>
  )
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
  className,
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
  htmlFor?: string
  className?: string
}) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function SaveIndicator({
  state,
  error,
  needsConfirmation,
}: {
  state: SaveState
  error: string | null
  needsConfirmation: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" aria-live="polite">
      {needsConfirmation && (
        <Chip tone="warn" icon={CircleAlert}>
          Needs your confirmation
        </Chip>
      )}
      {state === "saving" || state === "pending" ? (
        <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          Saving
        </span>
      ) : state === "saved" ? (
        <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
          <Check className="size-3.5" aria-hidden="true" />
          Saved
        </span>
      ) : state === "error" ? (
        <span className="text-sm text-danger" role="alert">
          Not saved: {error}
        </span>
      ) : null}
    </div>
  )
}

/** Chip tone for each campaign status. */
export const toneForStatus = {
  active: "good",
  draft: "neutral",
  paused: "warn",
  archived: "line",
} as const
