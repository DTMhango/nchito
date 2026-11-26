import { useQuery } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { useSearch } from "@tanstack/react-router"
import { PageHeader } from "@/components/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { connectionsQuery, type ConnectionProvider } from "./api"
import { ConnectionCard } from "./connection-card"
import { ConnectForm, OAuthButton } from "./connect-form"

type Block = {
  id: string
  title: string
  lead: ReactNode
  providers: ConnectionProvider[]
  add: ReactNode
}

const BLOCKS: Block[] = [
  {
    id: "gmail",
    title: "Gmail",
    providers: ["gmail"],
    lead: (
      <>
        For applying by email and spotting replies. Google's read permission
        covers your <b>whole mailbox</b>, even though this app only reads the
        label or search you choose. Use a separate mailbox just for the job
        search.
      </>
    ),
    add: <OAuthButton provider="gmail" label="Connect Gmail" />,
  },
  {
    id: "imap",
    title: "Other mailbox (IMAP and SMTP)",
    providers: ["imap_smtp"],
    lead: "Any other mailbox, with an app password. No cloud console needed.",
    add: <ConnectForm provider="imap_smtp" label="Mailbox" />,
  },
  {
    id: "drive",
    title: "Google Drive",
    providers: ["gdrive"],
    lead: "Keeps a copy of each application's final files in one folder, and makes share links when a posting wants a link. It can only see files it puts there.",
    add: <OAuthButton provider="gdrive" label="Connect Google Drive" />,
  },
  {
    id: "telegram",
    title: "Telegram",
    providers: ["telegram"],
    lead: "A bot that messages you, with Approve and Open buttons that open the app.",
    add: <ConnectForm provider="telegram" label="Telegram bot" />,
  },
  {
    id: "webhook",
    title: "Webhook",
    providers: ["webhook"],
    lead: "Any other place to send notifications to, as a signed web request.",
    add: <ConnectForm provider="webhook" label="Webhook" />,
  },
  {
    id: "search",
    title: "Search API",
    providers: ["search_api"],
    lead: "The key the web search source uses. Any search provider that answers in JSON works: say where the key goes and where the result links are. Test runs one search.",
    add: <ConnectForm provider="search_api" label="Search API" />,
  },
]

/** Where Google sends the owner back after consent: `?connected=gmail|gdrive`. */
const RETURNED: Record<string, string> = {
  gmail: "Gmail is connected.",
  gdrive: "Google Drive is connected.",
}

export function ConnectionsPage() {
  const q = useQuery(connectionsQuery())
  const search: { connected?: unknown } = useSearch({ strict: false })
  const returned =
    typeof search.connected === "string" ? RETURNED[search.connected] : null
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Connections"
        description="Mail, storage, chat and search accounts. Each shows what you allowed and what the app really reads. Passwords and tokens are encrypted and never shown again."
      />
      {returned && (
        <p
          role="status"
          className="rounded-sm bg-good-soft px-3 py-2 text-good"
        >
          {returned} Test it below to check it works.
        </p>
      )}
      {q.isPending && <Skeleton className="h-40 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-danger">
          Could not load connections. Check your connection and reload.
        </p>
      )}
      {q.isSuccess &&
        BLOCKS.map((b) => {
          const mine = q.data.filter((c) =>
            b.providers.includes(c.provider as ConnectionProvider)
          )
          return (
            <section
              key={b.id}
              aria-labelledby={`conn-${b.id}`}
              className="grid gap-3 panel p-4"
            >
              <div>
                <h3 id={`conn-${b.id}`} className="text-md">
                  {b.title}
                </h3>
                <p className="max-w-[70ch] text-muted-foreground">{b.lead}</p>
              </div>
              {mine.length > 0 && (
                <ul
                  aria-label={`${b.title} connections`}
                  className="grid gap-2"
                >
                  {mine.map((c) => (
                    <ConnectionCard key={c.id} c={c} />
                  ))}
                </ul>
              )}
              {b.add}
            </section>
          )
        })}
    </div>
  )
}
