import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/chip"
import { ThemeSwatch } from "@/features/settings/theme-swatch"
import { useTheme } from "@/themes/provider"
import {
  connectionsQuery,
  type ConnectionProvider,
} from "@/features/settings/connections/api"
import {
  ConnectForm,
  OAuthButton,
} from "@/features/settings/connections/connect-form"
import { ConnectionCard } from "@/features/settings/connections/connection-card"
import {
  sourceKeys,
  sourcesQuery,
  toSourceInput,
  updateSource,
} from "@/features/sources/api"
import { campaignsQuery } from "@/features/campaigns/api"
import { useReview } from "@/features/kit/api"
import { CRITERION_LABEL } from "../criteria"
import { startDryRun } from "../api"
import type { Local } from "../state"

/** Step: switch on the sources to search. Adding new boards happens on the Sources screen. */
export function SourcesStep({ next }: { next: () => void }) {
  const qc = useQueryClient()
  const q = useQuery(sourcesQuery())
  const toggle = useMutation({
    mutationFn: (s: NonNullable<typeof q.data>[number]) =>
      updateSource(s.id, { ...toSourceInput(s), enabled: !s.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: sourceKeys.sources }),
  })
  const sources = q.data ?? []
  return (
    <div className="grid max-w-[600px] gap-3">
      {q.isSuccess && sources.length === 0 && (
        <p className="text-muted-foreground">No sources yet.</p>
      )}
      <ul aria-label="Sources" className="grid gap-1.5">
        {sources.map((s) => (
          <li key={s.id}>
            <label className="flex items-center gap-2.5 rounded-md border border-border bg-surface px-3 py-2">
              <Checkbox
                checked={s.enabled}
                onCheckedChange={() => toggle.mutate(s)}
                aria-label={`Search ${s.name}`}
              />
              <span className="flex-1 font-medium">{s.name}</span>
              <span className="text-sm text-muted-foreground">
                {s.connector}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <p className="text-sm text-muted-foreground">
        To add a company careers page or another board, use{" "}
        <Link to="/sources" className="underline">
          Sources
        </Link>
        . You can come back here.
      </p>
      <div>
        <Button onClick={next}>Continue</Button>
      </div>
    </div>
  )
}

const MAIL: ConnectionProvider[] = ["gmail", "imap_smtp"]

/** Step: connect a mailbox. Optional. */
export function MailStep({
  next,
  skip,
}: {
  next: () => void
  skip: () => void
}) {
  const q = useQuery(connectionsQuery())
  const mine = (q.data ?? []).filter((c) =>
    MAIL.includes(c.provider as ConnectionProvider)
  )
  return (
    <div className="grid max-w-[620px] gap-4">
      <p className="rounded-sm bg-info-soft px-3 py-2 text-info">
        Use a mailbox just for the job search. Gmail's read permission covers
        the whole mailbox, even though the app reads only the label or search
        you choose.
      </p>
      {mine.length > 0 && (
        <ul aria-label="Connected mailboxes" className="grid gap-2">
          {mine.map((c) => (
            <ConnectionCard key={c.id} c={c} />
          ))}
        </ul>
      )}
      <div className="grid gap-2">
        <h3 className="text-md">Gmail</h3>
        <OAuthButton provider="gmail" label="Connect Gmail" />
      </div>
      <details className="rounded-md border border-border p-3">
        <summary className="cursor-pointer font-semibold">
          Another mailbox (IMAP and SMTP)
        </summary>
        <div className="mt-3">
          <ConnectForm provider="imap_smtp" label="Mailbox" />
        </div>
      </details>
      <div className="flex gap-2">
        <Button onClick={next} disabled={mine.length === 0}>
          Continue
        </Button>
        <Button variant="outline" onClick={skip}>
          Skip, I will do this later
        </Button>
      </div>
    </div>
  )
}

/** Step: look at scored results before anything is switched on. */
export function DryRunStep({
  local,
  next,
}: {
  local: Local
  next: () => void
}) {
  const qc = useQueryClient()
  const campaigns = useQuery(campaignsQuery())
  const review = useReview()
  const campaign =
    campaigns.data?.find((c) => c.id === local.campaignId) ??
    campaigns.data?.[0]
  const run = useMutation({
    mutationFn: () => startDryRun((campaign as { id: string }).id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["onboarding", "dry-runs"] }),
  })
  const waiting = review.data?.length ?? 0
  return (
    <div className="grid max-w-[620px] gap-4">
      {!campaign && (
        <p role="status" className="text-warn">
          Save your criteria first, so there is a campaign to try.
        </p>
      )}
      {campaign && (
        <p>
          Campaign: <b>{campaign.name}</b>{" "}
          <Chip tone={campaign.review_state === "confirmed" ? "good" : "warn"}>
            {campaign.review_state === "confirmed"
              ? "Criteria confirmed"
              : "Criteria not confirmed"}
          </Chip>
        </p>
      )}
      {local.decideLater.length > 0 && (
        <p
          role="status"
          className="rounded-sm bg-warn-soft px-3 py-2 text-warn"
        >
          Still undecided:{" "}
          {local.decideLater.map((k) => CRITERION_LABEL[k]).join(", ")}.
          Automation stays off until you set them.
        </p>
      )}
      {waiting > 0 && (
        <p>
          {waiting} item{waiting === 1 ? "" : "s"} still waiting for your review
          in the Kit.
        </p>
      )}
      <p className="text-muted-foreground">
        A dry run looks at real postings and scores them, but sends and changes
        nothing. The campaign starts in Prepare mode and can be raised later, on
        purpose, from Autopilot.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          onClick={() => run.mutate()}
          disabled={!campaign || run.isPending}
        >
          Run a dry run
        </Button>
        {run.isSuccess && (
          <>
            <span role="status" className="text-good">
              Started.
            </span>
            <Link to="/autopilot/runs" className="underline">
              See it in run history
            </Link>
          </>
        )}
        <Button variant="outline" onClick={next}>
          Continue
        </Button>
      </div>
      {run.isError && (
        <p role="alert" className="text-sm text-danger">
          {run.error.message}
        </p>
      )}
    </div>
  )
}

/** Step: pick a theme. */
export function LookStep() {
  const { themes, theme, setAppearance } = useTheme()
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {themes.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-pressed={t.id === theme.id}
            onClick={() => setAppearance({ theme_id: t.id })}
            className="flex items-center gap-2 rounded-sm border border-border bg-surface px-2.5 py-2 text-left font-medium aria-pressed:border-primary aria-pressed:shadow-[0_0_0_2px_var(--t-ring)]"
          >
            <ThemeSwatch theme={t} />
            {t.name}
          </button>
        ))}
      </div>
      <p className="text-muted-foreground">
        Where you hear about things is set under{" "}
        <Link to="/settings/notifications" className="underline">
          Notifications
        </Link>
        .
      </p>
    </div>
  )
}
