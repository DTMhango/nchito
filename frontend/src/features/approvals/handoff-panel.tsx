import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Copy, Download, ExternalLink } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { SectionHeader } from "@/components/page-header"
import { AppliedMyselfDialog } from "@/features/applications/applied-myself-dialog"
import { handoffQuery, type ApplicationSummary } from "@/features/autopilot/api"

const fileName = (url: string) =>
  decodeURIComponent(url.split("?")[0].split("/").pop() ?? "file")

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`${what} copied.`)
  } catch {
    toast.error("Couldn't copy. Select the text and copy it yourself.")
  }
}

/**
 * "Apply yourself" kit for owner-channel roles: the documents, the answers to paste and the
 * link, then "I applied" with evidence (the wave 1 dialog). Nothing counts as sent until
 * the owner records it.
 */
export function HandoffPanel({ app }: { app: ApplicationSummary }) {
  const q = useQuery(handoffQuery(app.id))
  const [recording, setRecording] = useState<ApplicationSummary | null>(null)
  const kit = q.data
  return (
    <section aria-label="Apply yourself" className="grid gap-3">
      <SectionHeader
        title="Apply yourself"
        aside="You submit this one. Nchito prepared everything."
      />
      {q.isPending && <p className="text-sm text-muted-foreground">Loading.</p>}
      {kit && (
        <div className="grid gap-4 rounded-lg border border-border bg-surface p-4">
          {kit.posting_url && (
            <Button asChild className="w-fit">
              <a
                href={kit.posting_url}
                target="_blank"
                rel="noreferrer noopener"
              >
                <ExternalLink aria-hidden="true" />
                Open the posting
              </a>
            </Button>
          )}
          <div className="grid gap-1.5">
            <h4 className="eyebrow">Documents to upload</h4>
            <ul className="grid gap-1">
              {kit.files.map((f) => (
                <li key={f}>
                  <a
                    href={f}
                    download
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-ink hover:underline"
                  >
                    <Download className="size-4" aria-hidden="true" />
                    {fileName(f)}
                  </a>
                </li>
              ))}
              {kit.files.length === 0 && (
                <li className="text-sm text-muted-foreground">
                  No documents yet.
                </li>
              )}
            </ul>
          </div>
          <div className="grid gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="eyebrow">Answers to paste</h4>
              <Button
                size="xs"
                variant="outline"
                onClick={() =>
                  void copy(
                    kit.answers
                      .map((a) => `${a.question}: ${a.answer}`)
                      .join("\n"),
                    "All answers"
                  )
                }
              >
                <Copy aria-hidden="true" />
                Copy all
              </Button>
            </div>
            <dl className="grid gap-1.5">
              {kit.answers.map((a, i) => (
                <div
                  key={`${a.question}-${i}`}
                  className="flex flex-wrap items-center gap-2 text-sm"
                >
                  <dt className="text-muted-foreground">{a.question}</dt>
                  <dd className="font-medium">{a.answer}</dd>
                  <Button
                    size="icon-xs"
                    variant="ghost"
                    aria-label={`Copy answer: ${a.question}`}
                    onClick={() => void copy(a.answer, "Answer")}
                  >
                    <Copy aria-hidden="true" />
                  </Button>
                </div>
              ))}
            </dl>
          </div>
          {kit.remaining_steps.length > 0 && (
            <div className="grid gap-1.5">
              <h4 className="eyebrow">Steps</h4>
              <ol className="grid list-decimal gap-1 pl-5 text-sm">
                {kit.remaining_steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
            <Button onClick={() => setRecording(app)}>I applied</Button>
            <span className="text-sm text-faint">
              Add the confirmation or the files you sent as evidence.
            </span>
          </div>
        </div>
      )}
      <AppliedMyselfDialog app={recording} onClose={() => setRecording(null)} />
    </section>
  )
}
