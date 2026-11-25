import type { ComponentProps, ReactNode } from "react"
import { cn } from "@/lib/utils"

/**
 * A4 preview frame. The page is always white paper with dark ink, in every theme and mode,
 * because it previews a document that will be printed or sent. Type inside scales with the
 * page width (container query units), so the preview reads the same at any size.
 */
export function PaperPreview({
  children,
  className,
  label = "Document preview",
}: {
  children: ReactNode
  className?: string
  label?: string
}) {
  return (
    <div
      role="region"
      aria-label={label}
      className={cn(
        "flex max-h-[calc(100vh-260px)] min-h-[360px] flex-col gap-3.5 overflow-auto rounded-lg bg-sunken p-3.5",
        className
      )}
    >
      {children}
    </div>
  )
}

type PaperPageProps = ComponentProps<"div"> & {
  variant?: "cv" | "letter"
  pageLabel?: string
}

export function PaperPage({
  children,
  className,
  variant = "cv",
  pageLabel,
  ...props
}: PaperPageProps) {
  return (
    <div
      className={cn(
        "@container aspect-[210/297] w-full max-w-full flex-none overflow-hidden bg-paper text-paper-ink shadow-[var(--paper-shadow)]",
        className
      )}
      {...props}
    >
      <div
        className={cn(
          "px-[7.5cqw] py-[7cqw] font-[family-name:var(--paper-font-body)]",
          variant === "cv"
            ? "text-[1.72cqw] leading-[1.45]"
            : "text-[1.9cqw] leading-[1.6]",
          "[&_h3]:font-[family-name:var(--paper-font-display)] [&_h3]:text-[4.6cqw] [&_h3]:font-semibold [&_h3]:tracking-[-0.01em] [&_h3]:text-paper-ink",
          "[&_h4]:mt-[3.2cqw] [&_h4]:mb-[1.4cqw] [&_h4]:border-b [&_h4]:border-paper-rule [&_h4]:pb-[0.8cqw] [&_h4]:font-[family-name:var(--paper-font-body)] [&_h4]:text-[1.6cqw] [&_h4]:font-semibold [&_h4]:tracking-[0.12em] [&_h4]:text-paper-muted [&_h4]:uppercase",
          "[&_p+p]:mt-[1.6cqw] [&_ul]:mt-[0.8cqw] [&_ul]:grid [&_ul]:list-disc [&_ul]:gap-[0.6cqw] [&_ul]:pl-[3cqw]"
        )}
      >
        {children}
        {pageLabel && (
          <div className="mt-[3cqw] text-right text-[1.4cqw] text-paper-muted">
            {pageLabel}
          </div>
        )}
      </div>
    </div>
  )
}
