import { cn } from "@/lib/utils"
import { EvidencePopover } from "./evidence-popover"

type FactTagProps = {
  /** Fact code, e.g. "F-112". */
  code: string
  /** The approved fact text. */
  text: string
  status?: "approved" | "draft" | "retired"
  className?: string
}

const STATUS_LABEL = {
  approved: "Approved fact",
  draft: "Draft fact, not yet approved",
  retired: "Retired fact",
}

/**
 * A fact ID pill that traces a line of a CV or letter to the Kit (DESIGN 5.1, 9).
 * Hover, tap or focus shows the fact's text.
 */
export function FactTag({
  code,
  text,
  status = "approved",
  className,
}: FactTagProps) {
  return (
    <EvidencePopover
      title={`${STATUS_LABEL[status]} ${code}`}
      content={text}
      triggerLabel={`${code}, ${STATUS_LABEL[status].toLowerCase()}`}
      triggerClassName={cn(
        "inline-flex items-center rounded-full border px-1.5 py-px num text-[0.72rem] font-semibold",
        status === "approved" &&
          "border-highlight bg-highlight-soft text-highlight-ink",
        status === "draft" &&
          "border-dashed border-warn bg-warn-soft text-warn",
        status === "retired" &&
          "border-border bg-sunken text-faint line-through",
        className
      )}
    >
      {code}
    </EvidencePopover>
  )
}
