import { Chip } from "@/components/chip"
import { groupChecks } from "@/features/studio/draft"
import type { MessageOut } from "./api"

/**
 * The checks on a message, grouped as the Studio groups them (blocking first, then warnings, then
 * what passed). A blocking result stops approval; questions are what the owner must decide.
 */
export function MessageChecks({ message }: { message: MessageOut }) {
  const groups = groupChecks(message.check_results)
  return (
    <section aria-label="Checks" className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold">Checks</h4>
        <Chip
          tone={
            message.check_status === "block"
              ? "danger"
              : message.check_status === "warn"
                ? "warn"
                : "good"
          }
          data-check-status={message.check_status}
        >
          {message.check_status === "block"
            ? `${groups.block.length} blocking`
            : message.check_status === "warn"
              ? `${groups.warn.length} to look at`
              : "All pass"}
        </Chip>
        {!message.checked && <Chip tone="warn">Edited since last check</Chip>}
      </div>
      {message.questions.length > 0 && (
        <div role="group" aria-label="Questions for you" className="grid gap-1">
          <p className="text-sm font-semibold">Decide before it can go:</p>
          <ul className="list-disc pl-5 text-sm">
            {message.questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      )}
      {[...groups.block, ...groups.warn].length > 0 && (
        <ul className="grid gap-1 text-sm">
          {[...groups.block, ...groups.warn].map((r, i) => (
            <li
              key={`${r.check}-${i}`}
              data-status={r.status}
              className="flex gap-2"
            >
              <Chip tone={r.status === "block" ? "danger" : "warn"}>
                {r.check}
              </Chip>
              <span className="min-w-0 break-words">{r.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
