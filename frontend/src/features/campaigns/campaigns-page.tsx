import {
  CalendarClock,
  Coins,
  Copy,
  Filter,
  Gauge,
  Radio,
  Target,
} from "lucide-react"
import { ScreenEmpty } from "@/components/empty-state"
import { View } from "@/components/view"

/** Campaigns: one search run on a schedule, with its own rules and budget (DESIGN 10.3). */
export function CampaignsPage() {
  return (
    <View>
      <ScreenEmpty
        icon={Target}
        title="Campaigns"
        lead="A campaign is one search you run on a schedule, with its own criteria, sources, scoring rubric, automation policy and budget. Imported campaigns arrive as drafts for you to confirm."
        firstStep={{
          label: "Create a campaign in the set-up guide",
          to: "/onboarding",
          hint: "Step 5 runs a dry run before anything is switched on.",
        }}
        items={[
          {
            icon: Filter,
            title: "Criteria",
            body: "Titles, keywords, locations, work models, seniority and pay floors, with include and exclude rules.",
          },
          {
            icon: Radio,
            title: "Sources",
            body: "Which boards, career pages and alert emails this campaign sweeps.",
          },
          {
            icon: Gauge,
            title: "Rubric with backtest",
            body: "Criteria weights and anchors, and how saved roles would score under a draft.",
          },
          {
            icon: CalendarClock,
            title: "Schedule",
            body: "When it sweeps, in your time zone.",
          },
          {
            icon: Coins,
            title: "Budget",
            body: "This campaign's share of the monthly AI cap.",
          },
          {
            icon: Copy,
            title: "Clone and preview",
            body: "Copy a campaign, and preview which roles a rule would match.",
          },
        ]}
      />
    </View>
  )
}
