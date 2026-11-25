import type { ReactNode } from "react"
import { ChevronLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type SplitViewProps = {
  /** The list column (tabs, filter bar, rows). */
  list: ReactNode
  /** The detail column for the selected item. */
  detail: ReactNode
  /**
   * On phones only one column shows. True shows the detail with a back button;
   * false shows the list. Ignored on wider screens, where both show.
   */
  showDetail: boolean
  onBack: () => void
  backLabel?: string
  className?: string
  listLabel?: string
}

/**
 * Inbox-style list + detail (Matches, Kit library). Becomes list -> detail on phones.
 * The detail region is a polite live region so selection changes are announced.
 */
export function SplitView({
  list,
  detail,
  showDetail,
  onBack,
  backLabel = "Back to the list",
  className,
  listLabel,
}: SplitViewProps) {
  return (
    <div
      data-show-detail={showDetail || undefined}
      className={cn(
        "group/split grid h-full min-h-0 grid-cols-1 md:grid-cols-[minmax(300px,390px)_minmax(0,1fr)]",
        className
      )}
    >
      <section
        aria-label={listLabel}
        className="flex min-h-0 min-w-0 flex-col group-data-[show-detail]/split:max-md:hidden md:border-r md:border-border"
      >
        {list}
      </section>
      <section
        aria-live="polite"
        className="min-h-0 min-w-0 overflow-auto pt-3 pb-10 max-md:hidden group-data-[show-detail]/split:max-md:block md:pt-5 md:pr-1 md:pl-7"
      >
        <Button
          variant="ghost"
          size="sm"
          className="mb-2.5 md:hidden"
          onClick={onBack}
        >
          <ChevronLeft data-icon="inline-start" aria-hidden="true" />
          {backLabel}
        </Button>
        {detail}
      </section>
    </div>
  )
}
