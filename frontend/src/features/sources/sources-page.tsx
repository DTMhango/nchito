import { Building2, HeartPulse, Link2, Mail, Radio, Rss } from "lucide-react"
import { ScreenEmpty } from "@/components/empty-state"
import { View } from "@/components/view"

/** Sources: the connector registry with health (DESIGN 6, 10.3). */
export function SourcesPage() {
  return (
    <View>
      <ScreenEmpty
        icon={Radio}
        title="Sources"
        lead="Where roles come from: job board APIs, applicant tracking boards, feeds, careers pages and job-alert emails. One failing source never stops a sweep."
        firstStep={{
          label: "Watch your first employer",
          to: "/campaigns",
          hint: "Or paste a careers page link; the board type is detected.",
        }}
        items={[
          {
            icon: HeartPulse,
            title: "Health",
            body: "Last success, failures and rate limits for every source.",
          },
          {
            icon: Building2,
            title: "Watched employers",
            body: "Employers whose boards are checked directly, with priority and cooldown.",
          },
          {
            icon: Link2,
            title: "Add by link",
            body: "Paste a careers URL; Greenhouse, Lever, Ashby, Workable or Workday is detected.",
          },
          {
            icon: Rss,
            title: "Feeds and APIs",
            body: "Remote boards and RSS feeds, re-read before trusting their remote labels.",
          },
          {
            icon: Mail,
            title: "Alert emails",
            body: "LinkedIn, Indeed and Glassdoor alerts read from your connected mailbox.",
          },
        ]}
      />
    </View>
  )
}
