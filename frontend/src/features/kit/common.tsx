import {
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentProps,
  type FormEvent,
  type ReactNode,
} from "react"
import { AlertTriangle, Check, Pencil, Search, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Chip } from "@/components/chip"
import { KeyHint } from "@/components/key-hint"
import { cn } from "@/lib/utils"
import {
  REVIEW_PAGE,
  useReview,
  useReviewDecision,
  type ReviewEntity,
} from "./api"

export const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong."

/** A native select dressed like the Input (compact, keyboard friendly, no portal). */
export function NativeSelect({
  className,
  ...props
}: ComponentProps<"select">) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        "h-8 min-w-0 rounded-md border field-focus border-input bg-surface px-2 text-sm text-foreground outline-none disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

/** Label above a control. The control gets the id so the label names it. */
export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string
  hint?: ReactNode
  children: (id: string) => ReactNode
  className?: string
}) {
  const id = useId()
  return (
    <div className={cn("grid gap-1", className)}>
      <label htmlFor={id} className="text-sm font-medium text-foreground">
        {label}
      </label>
      {children(id)}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

/** Search box; press "/" anywhere on the page to jump to it. */
export function SearchBox({
  value,
  onChange,
  placeholder,
  label = "Search",
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  label?: string
}) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return
      if (t?.isContentEditable) return
      e.preventDefault()
      ref.current?.focus()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])
  return (
    <div className="relative min-w-[200px] flex-1 sm:max-w-sm">
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-2.5 size-[15px] -translate-y-1/2 text-faint"
      />
      <input
        ref={ref}
        type="search"
        aria-label={label}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onChange("")
        }}
        className="h-8 w-full rounded-md border field-focus border-input bg-surface pr-9 pl-8 text-sm outline-none placeholder:text-faint"
      />
      {!value && (
        <KeyHint
          keys="/"
          className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2"
        />
      )}
    </div>
  )
}

/** A pressed / not pressed pill for filters and per-row switches. */
export function PillToggle({
  pressed,
  onPressedChange,
  children,
  className,
  ...props
}: Omit<ComponentProps<"button">, "onChange"> & {
  pressed: boolean
  onPressedChange: (next: boolean) => void
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onPressedChange(!pressed)}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-sm font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-primary-ink",
        pressed
          ? "border-primary bg-primary-soft text-primary-ink"
          : "border-border bg-surface text-muted-foreground hover:border-border-strong hover:text-foreground",
        className
      )}
      {...props}
    >
      {pressed && <Check aria-hidden="true" className="size-[13px]" />}
      {children}
    </button>
  )
}

/** Loading and error states for a query. Renders children once there is data. */
export function QueryGate<T>({
  query,
  children,
}: {
  query: {
    data: T | undefined
    isPending: boolean
    isError: boolean
    error: unknown
    refetch: () => unknown
  }
  children: (data: T) => ReactNode
}) {
  if (query.isPending)
    return (
      <div className="grid gap-2" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
    )
  if (query.isError || query.data === undefined)
    return (
      <div
        role="alert"
        className="flex items-center gap-3 rounded-md border border-danger bg-danger-soft px-3.5 py-3 text-danger"
      >
        <AlertTriangle aria-hidden="true" className="size-4" />
        <span className="flex-1">{errorText(query.error)}</span>
        <Button
          size="sm"
          variant="outline"
          onClick={() => void query.refetch()}
        >
          Try again
        </Button>
      </div>
    )
  return <>{children(query.data)}</>
}

/** Two-step delete: first press asks, second press does it. */
export function ConfirmButton({
  label = "Delete",
  confirmLabel = "Sure? Delete",
  onConfirm,
  disabled,
}: {
  label?: string
  confirmLabel?: string
  onConfirm: () => void
  disabled?: boolean
}) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(t)
  }, [armed])
  return (
    <Button
      type="button"
      size="sm"
      variant={armed ? "destructive" : "ghost"}
      disabled={disabled}
      onClick={() => (armed ? onConfirm() : setArmed(true))}
    >
      <Trash2 aria-hidden="true" />
      {armed ? confirmLabel : label}
    </Button>
  )
}

/** A form in a dialog: title, fields, Save / Cancel, inline error. */
export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  onSubmit,
  saving,
  error,
  children,
  submitLabel = "Save",
  wide,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  onSubmit: () => void
  saving?: boolean
  error?: unknown
  children: ReactNode
  submitLabel?: string
  wide?: boolean
}) {
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(wide && "sm:max-w-2xl")}>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className={description ? undefined : "sr-only"}>
              {description ?? title}
            </DialogDescription>
          </DialogHeader>
          <div className="grid max-h-[62vh] gap-3.5 overflow-y-auto p-0.5">
            {children}
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {errorText(error)}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving" : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Needs review (DESIGN 13): imported items wait until confirmed, edited or dropped.
// ---------------------------------------------------------------------------

/** Review items that belong to one Kit page. */
export function useReviewFor(page: string) {
  const q = useReview()
  const items = (q.data ?? []).filter((i) => REVIEW_PAGE[i.entity] === page)
  return { items, count: items.length }
}

/** Counts per Kit page, for the sub-nav badges. */
export function useReviewCounts() {
  const q = useReview()
  const counts: Record<string, number> = {}
  for (const i of q.data ?? []) {
    const p = REVIEW_PAGE[i.entity]
    if (p) counts[p] = (counts[p] ?? 0) + 1
  }
  return counts
}

/** Confirm / Edit / Drop for one item waiting for review. */
export function ReviewActions({
  entity,
  id,
  label,
  onEdit,
}: {
  entity: ReviewEntity
  id: string
  label: string
  onEdit?: () => void
}) {
  const decide = useReviewDecision()
  const run = (decision: "confirm" | "drop") =>
    decide.mutate(
      { entity, id, decision },
      {
        onSuccess: () =>
          toast.success(decision === "confirm" ? "Confirmed." : "Dropped."),
        onError: (e) => toast.error(errorText(e)),
      }
    )
  return (
    <span
      className="inline-flex items-center gap-1"
      role="group"
      aria-label={`Review ${label}`}
    >
      <Button
        size="xs"
        variant="outline"
        disabled={decide.isPending}
        onClick={() => run("confirm")}
        aria-label={`Confirm ${label}`}
      >
        <Check aria-hidden="true" />
        Confirm
      </Button>
      {onEdit && (
        <Button
          size="xs"
          variant="ghost"
          onClick={onEdit}
          aria-label={`Edit ${label}`}
        >
          <Pencil aria-hidden="true" />
          Edit
        </Button>
      )}
      <Button
        size="xs"
        variant="ghost"
        disabled={decide.isPending}
        onClick={() => run("drop")}
        aria-label={`Drop ${label}`}
        className="hover:text-danger"
      >
        <X aria-hidden="true" />
        Drop
      </Button>
    </span>
  )
}

/** Banner at the top of a Kit page: how many items wait, with a filter switch. */
export function ReviewBanner({
  count,
  only,
  onOnlyChange,
}: {
  count: number
  only: boolean
  onOnlyChange: (v: boolean) => void
}) {
  if (count === 0 && !only) return null
  return (
    <div
      role="status"
      className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-warn bg-warn-soft px-3.5 py-2.5"
    >
      <span className="font-medium text-foreground">
        {count === 0
          ? "Nothing left to review."
          : `${count} ${count === 1 ? "item needs" : "items need"} your review.`}
      </span>
      <span className="text-sm text-muted-foreground">
        Imported items wait until you confirm, edit or drop them.
      </span>
      <PillToggle
        pressed={only}
        onPressedChange={onOnlyChange}
        className="ml-auto"
      >
        Needs review only
      </PillToggle>
    </div>
  )
}

export function NeedsReviewChip() {
  return (
    <Chip tone="warn" title="Imported, not yet confirmed">
      Needs review
    </Chip>
  )
}

/** Sentence-case helper text under a list. */
export function ListEmpty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-md border border-dashed border-border-strong px-4 py-8 text-center text-muted-foreground">
      {children}
    </p>
  )
}
