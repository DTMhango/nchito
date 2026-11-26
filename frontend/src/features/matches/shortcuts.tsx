import { useEffect, useRef } from "react"
import { KeyHint } from "@/components/key-hint"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

export const SHORTCUTS: [string[], string][] = [
  [["J"], "Next role"],
  [["K"], "Previous role"],
  [["T"], "Tailor documents"],
  [["A"], "Apply"],
  [["S"], "Skip"],
  [["Z"], "Snooze (then 1 to 4)"],
  [["P"], "Pin or unpin"],
  [["X"], "Select or deselect for bulk actions"],
  [["/"], "Search"],
  [["Esc"], "Clear the selection, or go back on a phone"],
  [["?"], "This list"],
]

export type KeyHandlers = Partial<Record<string, (e: KeyboardEvent) => void>>

function isTyping(t: EventTarget | null) {
  const el = t as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable
  )
}

/** Something modal is open (dialog, sheet, menu): page keys stand down. */
function overlayOpen() {
  return !!document.querySelector(
    '[role="dialog"], [role="alertdialog"], [role="menu"], [data-slot="popover-content"]'
  )
}

/** Single-key shortcuts for the Matches screen. Keys are matched lower-case, plus "?" and "/". */
export function useMatchesKeys(handlers: KeyHandlers) {
  const ref = useRef(handlers)
  useEffect(() => {
    ref.current = handlers
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return
      if (isTyping(e.target) || overlayOpen()) return
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
      const h = ref.current[key]
      if (h) {
        e.preventDefault()
        h(e)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])
}

export function ShortcutSheet({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-4 pop-surface p-5 sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle className="heading text-md">
            Keyboard shortcuts
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            They work anywhere on Matches unless you are typing.
          </DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 text-sm">
          {SHORTCUTS.map(([keys, text]) => (
            <div key={text} className="contents">
              <dt>
                <KeyHint keys={keys} />
              </dt>
              <dd className="text-muted-foreground">{text}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  )
}
