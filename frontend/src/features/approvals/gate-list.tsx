import { CircleCheck, CircleHelp, CircleX } from "lucide-react"
import { Chip, type ChipTone } from "@/components/chip"
import {
  autoVerdict,
  gateName,
  gateState,
  GATE_STATE_TEXT,
  type GateState,
} from "@/features/autopilot/logic"
import type { GateResult } from "@/features/autopilot/api"

const STATE_VIEW: Record<
  GateState,
  { tone: ChipTone; icon: typeof CircleCheck }
> = {
  pass: { tone: "good", icon: CircleCheck },
  fail: { tone: "danger", icon: CircleX },
  unknown: { tone: "warn", icon: CircleHelp },
}

/**
 * "Why can or can't this go automatically": every gate with its reason. A gate the server
 * could not decide is shown as Unknown, never as a pass (DESIGN 8.1, unknown is not yes).
 */
export function GateList({
  gates,
  label,
}: {
  gates: readonly GateResult[]
  /** A second list (for example the gates of a refusal) needs its own name. */
  label?: string
}) {
  const verdict = autoVerdict(gates)
  return (
    <section
      aria-label={label ?? "Automatic sending checks"}
      className="grid gap-2"
    >
      <h4 className="eyebrow">
        {label ?? "Why this can or cannot go automatically"}
      </h4>
      <p
        className="text-sm font-medium"
        data-verdict={verdict.canAuto ? "auto" : "ask"}
      >
        {verdict.headline}
      </p>
      <ul className="grid gap-1.5">
        {gates.map((g) => {
          const s = gateState(g)
          const v = STATE_VIEW[s]
          return (
            <li
              key={g.gate}
              data-state={s}
              className="grid gap-0.5 rounded-md border border-border bg-surface px-3 py-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={v.tone} icon={v.icon}>
                  {GATE_STATE_TEXT[s]}
                </Chip>
                <span className="text-sm font-medium">{gateName(g.gate)}</span>
              </div>
              {g.detail && (
                <p className="text-sm text-muted-foreground">{g.detail}</p>
              )}
              {s === "unknown" && (
                <p className="text-xs text-faint">
                  Unknown counts as not passed. It needs your approval.
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
