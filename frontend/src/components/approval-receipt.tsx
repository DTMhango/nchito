import type { ReactNode } from "react"
import {
  AlertTriangle,
  FileText,
  Globe,
  Mail,
  Paperclip,
  ShieldCheck,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Chip } from "./chip"

export type ReceiptAnswer = {
  question: string
  answer: string
  material?: boolean
}
export type ReceiptAttachment = { name: string; kind: string; hash?: string }
export type ReceiptChange = { field: string; from: string; to: string }

type ApprovalReceiptProps = {
  employer: string
  role: string
  /** Verified destination: an email address or an application domain. */
  destination: { kind: "email" | "web"; value: string; verified: boolean }
  packetVersion?: string
  pay?: string
  /** Pay and work-rights answers, plus any other material answers. */
  answers: ReceiptAnswer[]
  attachments: ReceiptAttachment[]
  /** Anything unusual being disclosed (a referee, an ID document, a salary figure). */
  disclosures?: string[]
  /** What changed since the owner last looked. */
  changes?: ReceiptChange[]
  /** The action label says what happens: "Send email to recruiter", "Let the agent submit". */
  approveLabel: string
  onApprove?: () => void
  onEdit?: () => void
  onDecline?: () => void
  footnote?: ReactNode
  className?: string
}

/**
 * The approval receipt (DESIGN 18.2): the one screen the owner approves from, built for a
 * phone. Approval binds to a versioned packet; any material change shows in "Changed since
 * you last looked". Layout shell for wave 0; the packet arrives in wave 2.
 */
export function ApprovalReceipt(p: ApprovalReceiptProps) {
  const DestIcon = p.destination.kind === "email" ? Mail : Globe
  return (
    <article
      aria-label={`Approve application to ${p.employer}`}
      className={cn(
        "mx-auto grid w-full max-w-[460px] overflow-hidden elev",
        p.className
      )}
    >
      <header className="grid gap-1 border-b border-border p-4.5">
        <div className="eyebrow">Approve application</div>
        <h3 className="text-lg">{p.role}</h3>
        <div className="text-muted-foreground">{p.employer}</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Chip tone={p.destination.verified ? "good" : "warn"} icon={DestIcon}>
            {p.destination.value}
          </Chip>
          {p.destination.verified ? (
            <Chip tone="line" icon={ShieldCheck}>
              Destination checked
            </Chip>
          ) : (
            <Chip tone="warn" icon={AlertTriangle}>
              Destination not verified
            </Chip>
          )}
          {p.packetVersion && (
            <Chip tone="line" className="num">
              {p.packetVersion}
            </Chip>
          )}
        </div>
      </header>

      {p.changes && p.changes.length > 0 && (
        <section className="grid gap-1.5 border-b border-border bg-warn-soft px-4.5 py-3 text-warn">
          <h4 className="eyebrow text-warn">Changed since you last looked</h4>
          <ul className="grid gap-1 text-sm">
            {p.changes.map((c) => (
              <li key={c.field}>
                <b className="font-semibold">{c.field}:</b>{" "}
                <s className="opacity-75">{c.from}</s> → {c.to}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="grid gap-2 border-b border-border px-4.5 py-3.5">
        <h4 className="eyebrow">What they will be told</h4>
        {p.pay && (
          <div className="flex justify-between gap-3 text-sm">
            <span className="text-muted-foreground">Advertised pay</span>
            <span className="num font-semibold">{p.pay}</span>
          </div>
        )}
        <dl className="grid gap-2">
          {p.answers.map((a) => (
            <div key={a.question} className="grid gap-0.5">
              <dt className="text-sm text-muted-foreground">
                {a.question}
                {a.material && (
                  <span className="sr-only"> (material answer)</span>
                )}
              </dt>
              <dd
                className={cn(
                  "font-medium",
                  a.material && "text-highlight-ink"
                )}
              >
                {a.answer}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="grid gap-2 border-b border-border px-4.5 py-3.5">
        <h4 className="eyebrow">Attachments</h4>
        <ul className="grid gap-1.5">
          {p.attachments.map((f) => (
            <li key={f.name} className="flex items-center gap-2 text-sm">
              {f.kind === "pdf" ? (
                <FileText className="size-4 text-faint" aria-hidden="true" />
              ) : (
                <Paperclip className="size-4 text-faint" aria-hidden="true" />
              )}
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              {f.hash && (
                <span className="num text-xs text-faint">{f.hash}</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {p.disclosures && p.disclosures.length > 0 && (
        <section className="grid gap-1.5 border-b border-border px-4.5 py-3.5">
          <h4 className="eyebrow">Also disclosed</h4>
          <ul className="grid gap-1 text-sm">
            {p.disclosures.map((d) => (
              <li key={d} className="flex gap-2">
                <AlertTriangle
                  className="mt-0.5 size-4 shrink-0 text-warn"
                  aria-hidden="true"
                />
                {d}
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className="grid gap-2 p-4.5">
        <Button size="lg" onClick={p.onApprove}>
          {p.approveLabel}
        </Button>
        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={p.onEdit}>
            Edit first
          </Button>
          <Button variant="ghost" className="flex-1" onClick={p.onDecline}>
            Not this one
          </Button>
        </div>
        {p.footnote && <p className="text-xs text-faint">{p.footnote}</p>}
      </footer>
    </article>
  )
}
