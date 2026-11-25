import { BarChart3, Clock, Coins, Filter, Globe, Layers } from "lucide-react"
import { ScreenEmpty } from "@/components/empty-state"
import { View } from "@/components/view"

/** Insights: how the search is going (DESIGN 10.3). Built in wave 4. */
export function InsightsPage() {
  return (
    <View>
      <ScreenEmpty
        icon={BarChart3}
        title="Insights"
        lead="How the search is going, and where your time and money work best. Charts fill in once applications have been out for a while."
        firstStep={{ label: "See today's work", to: "/today" }}
        items={[
          {
            icon: Filter,
            title: "Funnel by campaign",
            body: "Found, shortlisted, applied, interview and offer, over time.",
          },
          {
            icon: Layers,
            title: "Response rate by track",
            body: "Which positioning of you gets replies.",
          },
          {
            icon: Globe,
            title: "By source and market",
            body: "Where replies come from: boards, portals, countries, remote.",
          },
          {
            icon: Clock,
            title: "Time in stage",
            body: "How long applications wait at each stage.",
          },
          {
            icon: Coins,
            title: "Spend",
            body: "AI cost by stage and model, per application and per interview.",
          },
        ]}
      />
    </View>
  )
}
