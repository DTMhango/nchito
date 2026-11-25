import { cn } from "@/lib/utils"

/** The app mark: an N on the primary colour with an accent dot. Theme-aware. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 28 28"
      aria-hidden="true"
      className={cn("size-7 shrink-0", className)}
    >
      <rect
        className="fill-primary"
        x="1"
        y="1"
        width="26"
        height="26"
        rx="8"
      />
      <path
        className="stroke-primary-foreground"
        d="M8.5 19.5V8.5l11 11V8.5"
        fill="none"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle className="fill-highlight" cx="19.5" cy="8.5" r="2.3" />
    </svg>
  )
}
