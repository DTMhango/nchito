import { cn } from "@/lib/utils"

const isMac =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)

/** Render "Mod" as Ctrl or ⌘ for the current platform. */
export function modKey() {
  return isMac ? "⌘" : "Ctrl"
}

type KeyHintProps = {
  /** One key ("T"), a chord ("Mod K") or several keys (["J", "K"]). */
  keys: string | string[]
  className?: string
  /** Inside a primary button the hint inherits the button's ink. */
  tone?: "default" | "inverse"
}

/** A keyboard shortcut hint, styled like a keycap. Decorative: the action keeps its own label. */
export function KeyHint({ keys, className, tone = "default" }: KeyHintProps) {
  const list = Array.isArray(keys) ? keys : [keys.replace(/\bMod\b/, modKey())]
  return (
    <span
      className={cn("inline-flex items-center gap-1", className)}
      aria-hidden="true"
    >
      {list.map((k) => (
        <kbd
          key={k}
          className={cn(
            "rounded-[max(0px,calc(var(--t-radius-sm)-2px))] border border-b-2 px-[5px] py-px num text-[0.7rem] leading-[1.3] whitespace-nowrap",
            tone === "default" &&
              "border-border bg-surface-2 text-muted-foreground",
            tone === "inverse" &&
              "border-current bg-transparent text-current opacity-75"
          )}
        >
          {k}
        </kbd>
      ))}
    </span>
  )
}
