import {
  Ban,
  Hourglass,
  MessageCircleQuestion,
  Play,
  type LucideIcon,
} from "lucide-react"
import { Chip, type ChipTone } from "@/components/chip"
import {
  useEmployerChips,
  type EmployerChip as ChipData,
  type EmployerState,
} from "./api"

const META: Record<
  Exclude<EmployerState, "free">,
  { tone: ChipTone; icon: LucideIcon }
> = {
  role_in_progress: { tone: "info", icon: Play },
  cooling_down: { tone: "warn", icon: Hourglass },
  always_ask_first: { tone: "accent", icon: MessageCircleQuestion },
  blocked: { tone: "danger", icon: Ban },
}

const FREE_ONLY: EmployerState[] = ["free"]

/**
 * The employer state: free, role in progress, cooling down until a date, always ask first, or
 * never apply. The text is the server's, so the date and the reason are always its own words.
 * `hide` lists states that add nothing in that place (free almost everywhere). `onApplication`
 * is for an application card or row, which is itself a role in progress: "role in progress"
 * shows only when another role at the employer is live, and says so.
 */
export function EmployerChip({
  chip,
  hide = FREE_ONLY,
  onApplication = false,
}: {
  /** A row's own state (Employers screens) carries no live counts; the per-job chip does. */
  chip:
    | (Pick<ChipData, "state" | "text"> &
        Partial<Pick<ChipData, "live" | "live_elsewhere">>)
    | undefined
  hide?: EmployerState[]
  onApplication?: boolean
}) {
  if (!chip || hide.includes(chip.state)) return null
  if (chip.state === "free")
    return onApplication ? null : <Chip tone="good">{chip.text}</Chip>
  let text = chip.text
  if (onApplication && chip.state === "role_in_progress") {
    const others = chip.live_elsewhere ?? 0
    if (others < 1) return null
    text = `${others} other role${others === 1 ? "" : "s"} in progress`
  }
  const m = META[chip.state]
  return (
    <Chip
      tone={m.tone}
      icon={m.icon}
      data-employer-state={chip.state}
      className="whitespace-normal"
    >
      {text}
    </Chip>
  )
}

/** The chip for one job, fetched on its own (the job page and the Matches detail pane). */
export function JobEmployerChip({ jobId }: { jobId: string }) {
  const chips = useEmployerChips([jobId])
  return <EmployerChip chip={chips[jobId]} />
}
