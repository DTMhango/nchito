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
 * `hide` lists states that add nothing in that place (free almost everywhere; "role in progress"
 * on an application card, which is itself the role in progress).
 */
export function EmployerChip({
  chip,
  hide = FREE_ONLY,
}: {
  chip: ChipData | undefined
  hide?: EmployerState[]
}) {
  if (!chip || hide.includes(chip.state)) return null
  if (chip.state === "free") return <Chip tone="good">{chip.text}</Chip>
  const m = META[chip.state]
  return (
    <Chip
      tone={m.tone}
      icon={m.icon}
      data-employer-state={chip.state}
      className="whitespace-normal"
    >
      {chip.text}
    </Chip>
  )
}

/** The chip for one job, fetched on its own (the job page and the Matches detail pane). */
export function JobEmployerChip({ jobId }: { jobId: string }) {
  const chips = useEmployerChips([jobId])
  return <EmployerChip chip={chips[jobId]} />
}
