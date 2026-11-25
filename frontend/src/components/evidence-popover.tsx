import { useRef, useState, type ReactNode } from "react"
import { Popover as PopoverPrimitive } from "radix-ui"
import { cn } from "@/lib/utils"

type EvidencePopoverProps = {
  /** The visible trigger content (a chip, a fact code, an underlined phrase). */
  children: ReactNode
  /** Small heading inside the popover, e.g. "From the posting" or "Approved fact F-112". */
  title?: ReactNode
  /** The evidence itself: a quote from the posting or a fact's text. */
  content: ReactNode
  /** Where it came from: "Posting, paragraph 3" or "Kit library". */
  source?: ReactNode
  triggerClassName?: string
  /** Accessible name of the trigger when its visible text is not enough. */
  triggerLabel?: string
  side?: "top" | "bottom" | "left" | "right"
}

/**
 * Shows the sentence behind a value (DESIGN 6.1). Opens on hover (mouse), on tap, and on
 * keyboard focus; closes on Escape, blur or pointer leave. Never steals focus.
 */
export function EvidencePopover({
  children,
  title,
  content,
  source,
  triggerClassName,
  triggerLabel,
  side = "bottom",
}: EvidencePopoverProps) {
  const [open, setOpen] = useState(false)
  const closeTimer = useRef<number | undefined>(undefined)
  const openNow = () => {
    window.clearTimeout(closeTimer.current)
    setOpen(true)
  }
  const closeSoon = () => {
    window.clearTimeout(closeTimer.current)
    closeTimer.current = window.setTimeout(() => setOpen(false), 120)
  }

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger
        type="button"
        aria-label={triggerLabel}
        className={cn("cursor-help rounded-xs", triggerClassName)}
        onPointerEnter={(e) => e.pointerType === "mouse" && openNow()}
        onPointerLeave={(e) => e.pointerType === "mouse" && closeSoon()}
        onFocus={openNow}
        onBlur={closeSoon}
      >
        {children}
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side={side}
          sideOffset={6}
          align="start"
          collisionPadding={16}
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onPointerEnter={openNow}
          onPointerLeave={closeSoon}
          role="tooltip"
          className="z-50 w-[280px] max-w-[calc(100vw-32px)] rounded-sm bg-foreground px-3 py-2.5 text-[0.82rem] leading-[1.4] text-background shadow-elev data-[state=open]:animate-in data-[state=open]:fade-in-0"
        >
          {title && (
            <b className="mb-1 block num text-[0.72rem] font-semibold opacity-80">
              {title}
            </b>
          )}
          <div>{content}</div>
          {source && (
            <div className="mt-1.5 text-[0.72rem] opacity-75">{source}</div>
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
