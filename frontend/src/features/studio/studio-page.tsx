import {
  CheckCheck,
  FileDiff,
  FileText,
  ListChecks,
  PenLine,
  Send,
  SquarePen,
} from "lucide-react"
import { ScreenEmpty } from "@/components/empty-state"
import { View } from "@/components/view"

/** Studio: tailor one application (DESIGN 9, 10.3). Built in wave 2. */
export function StudioPage() {
  return (
    <View>
      <ScreenEmpty
        icon={SquarePen}
        title="Studio"
        lead="Where one application's CV, letter and form answers are tailored, checked and approved. Every line traces to an approved fact from your Kit."
        firstStep={{
          label: "Choose a role in Matches",
          to: "/matches",
          hint: "Press T on any match to open it here.",
        }}
        items={[
          {
            icon: ListChecks,
            title: "Requirements and keywords",
            body: "The posting's requirements, each matched Strong, Partial or Gap, and keyword coverage.",
          },
          {
            icon: PenLine,
            title: "Structured editor",
            body: "Headline, summary and bullets you can edit and reorder, each tagged with the fact behind it.",
          },
          {
            icon: FileText,
            title: "Live A4 preview",
            body: "CV, cover letter and answers on white paper, exactly as they will be sent.",
          },
          {
            icon: CheckCheck,
            title: "Checks strip",
            body: "Facts traced, guardrails, length and keywords. Edits re-run the checks.",
          },
          {
            icon: FileDiff,
            title: "Diff against your base CV",
            body: "What changed for this role, beside the approved wording.",
          },
          {
            icon: Send,
            title: "Approve and apply",
            body: "Pick the channel: email, browser agent or apply yourself.",
          },
        ]}
      />
    </View>
  )
}
