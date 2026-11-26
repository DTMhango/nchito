import { Link } from "@tanstack/react-router"
import { FileText, Mail, MessagesSquare, type LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"

type Coming = {
  icon: LucideIcon
  wave: 2 | 3
  title: string
  body: string
  items: string[]
}

const COMING = {
  documents: {
    icon: FileText,
    wave: 2,
    title: "CV, letter and attachments",
    body: "Drafts open in the Studio. After you apply, this tab shows the exact files that were sent, read-only.",
    items: [
      "The CV and letter as sent",
      "Attachments, with their checksums",
      "A link to open the draft in the Studio",
    ],
  },
  messages: {
    icon: Mail,
    wave: 2,
    title: "Email about this role",
    body: "Threads linked to this role appear with their classification: confirmation, rejection or interview. You can draft a reply or a follow-up from here.",
    items: [
      "Threads with a classification chip",
      "Replies and follow-ups drafted from your facts",
      "Threads that need your review",
    ],
  },
  interview: {
    icon: MessagesSquare,
    wave: 3,
    title: "Interview pack",
    body: "Built when the stage becomes interview, or on request, from the posting, what you sent and your approved facts.",
    items: [
      "Role and company briefs, with sources",
      "Likely questions with answers built from your facts",
      "Your gaps, and what you told them on the form",
      "Pay position, questions to ask, and one entry per round",
    ],
  },
} as const satisfies Record<string, Coming>

/** A designed placeholder for a tab that arrives in a later wave, saying what will appear. */
export function ComingTab({
  tab,
  applicationId,
}: {
  tab: keyof typeof COMING
  applicationId?: string | null
}) {
  const c: Coming = COMING[tab]
  return (
    <div className="rounded-lg border border-dashed border-border-strong">
      <EmptyState
        icon={c.icon}
        title={
          <span className="inline-flex flex-wrap items-center justify-center gap-2">
            {c.title} <Chip tone="line">Arrives in wave {c.wave}</Chip>
          </span>
        }
        description={c.body}
        actions={
          tab === "documents" && applicationId ? (
            <Button asChild size="sm" variant="outline">
              <Link to="/studio" search={{ application: applicationId }}>
                Open the Studio
              </Link>
            </Button>
          ) : undefined
        }
      />
      <ul className="mx-auto mb-6 grid max-w-[46ch] list-disc gap-1 pl-5 text-sm text-muted-foreground">
        {c.items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  )
}
