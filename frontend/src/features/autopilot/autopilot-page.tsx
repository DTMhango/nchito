import {
  CalendarClock,
  Gauge,
  History,
  ListChecks,
  MonitorSmartphone,
  ShieldQuestion,
  SlidersHorizontal,
} from "lucide-react"
import { ScreenEmpty } from "@/components/empty-state"
import { View } from "@/components/view"
import { useAutopilot } from "@/app/shell/autopilot-switch"

/** Autopilot: what the system may do on its own (DESIGN 8.1, 10.3). Built in wave 2. */
export function AutopilotPage() {
  const { state } = useAutopilot()
  return (
    <View>
      <ScreenEmpty
        icon={Gauge}
        title="Autopilot"
        status={state.paused ? "Paused" : "Nothing to run yet"}
        lead="Decide how far the system may go on its own: save only, prepare documents, ask you then apply, or apply automatically inside your limits. New campaigns start at Prepare."
        firstStep={{
          label: "Set up a campaign first",
          to: "/campaigns",
          hint: "Autopilot acts on campaigns, so it has nothing to do until one exists.",
        }}
        items={[
          {
            icon: SlidersHorizontal,
            title: "Mode and thresholds",
            body: "Shortlist, tailor and auto-apply lines on one track over this month's scores, with how many roles each setting would have caught.",
          },
          {
            icon: CalendarClock,
            title: "Limits",
            body: "Daily and weekly caps, quiet hours, employer cooldown and your time zone.",
          },
          {
            icon: MonitorSmartphone,
            title: "Channels and runners",
            body: "Email, the browser agent on your PC or a server, and manual handoff, with when each was last seen.",
          },
          {
            icon: ShieldQuestion,
            title: "Always ask me first",
            body: "Rules that stop for your approval: a salary figure, a new question, a new portal account.",
          },
          {
            icon: History,
            title: "Run history",
            body: "Every sweep, tailoring batch and agent run, with counts, time, cost and errors.",
          },
          {
            icon: ListChecks,
            title: "Dry run",
            body: "See what would happen at the current settings before anything is switched on.",
          },
        ]}
      />
    </View>
  )
}
