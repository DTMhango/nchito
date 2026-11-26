import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { Chip, type ChipTone } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { NativeSelect } from "@/features/campaigns/bits"
import { runnersQuery } from "@/features/autopilot/api"
import { accountsQuery, accountKeys, saveAccount } from "./api"
import { ACCOUNT_STATUS_LABEL, accountStatusText, dateText } from "./logic"
import type {
  PortalAccount,
  PortalAccountIn,
  PortalAccountStatus,
} from "./w3-pending-types"

const TONE: Record<PortalAccountStatus, ChipTone> = {
  none: "neutral",
  created: "info",
  signed_in: "good",
}

/** Portal accounts: one row per employer portal. The email used is kept; a password never is. */
export function AccountsPage() {
  const q = useQuery(accountsQuery())
  const [editing, setEditing] = useState<PortalAccount | "new" | null>(null)
  return (
    <div className="grid gap-5">
      <PageHeader
        title="Portal accounts"
        description="Employer portals that need an account. You create the account and sign in yourself, in the browser your runner uses. This list only keeps track of where you got to. No passwords are stored or asked for here."
        actions={
          <Button onClick={() => setEditing("new")}>
            <Plus aria-hidden="true" /> Add a portal
          </Button>
        }
      />
      {editing && (
        <AccountForm
          key={editing === "new" ? "new" : editing.id}
          account={editing === "new" ? null : editing}
          onDone={() => setEditing(null)}
        />
      )}
      {q.isPending && <Skeleton className="h-32 w-full bg-sunken" />}
      {q.isError && (
        <p role="alert" className="text-danger">
          Could not load portal accounts. Reload to try again.
        </p>
      )}
      {q.isSuccess && q.data.length === 0 && (
        <EmptyState
          title="No portals yet"
          description="A portal appears here when a role needs an account, or you can add one."
        />
      )}
      {q.isSuccess && q.data.length > 0 && (
        <ul aria-label="Portal accounts" className="grid gap-2.5">
          {q.data.map((a) => (
            <li
              key={a.id}
              className="grid gap-1.5 rounded-lg border border-border bg-surface p-3.5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-md">{a.portal_name}</h3>
                <Chip tone={TONE[a.status]}>{accountStatusText(a)}</Chip>
                {a.applications_waiting > 0 && (
                  <Chip tone="warn">
                    {a.applications_waiting} application
                    {a.applications_waiting === 1 ? "" : "s"} waiting
                  </Chip>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  aria-label={`Edit ${a.portal_name}`}
                  onClick={() => setEditing(a)}
                >
                  Edit
                </Button>
              </div>
              <p className="text-sm text-muted-foreground">
                <a
                  href={a.portal_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="underline underline-offset-2"
                >
                  {a.portal_url}
                </a>
              </p>
              <p className="text-sm text-faint">
                Email used: {a.email_used ?? "not recorded"} · Last sign-in:{" "}
                {dateText(a.last_sign_in_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function AccountForm({
  account,
  onDone,
}: {
  account: PortalAccount | null
  onDone: () => void
}) {
  const qc = useQueryClient()
  const runners = useQuery(runnersQuery())
  const [name, setName] = useState(account?.portal_name ?? "")
  const [url, setUrl] = useState(account?.portal_url ?? "")
  const [status, setStatus] = useState<PortalAccountStatus>(
    account?.status ?? "none"
  )
  const [runner, setRunner] = useState(account?.signed_in_runner ?? "")
  const [email, setEmail] = useState(account?.email_used ?? "")
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: (body: PortalAccountIn) =>
      saveAccount(account?.id ?? null, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: accountKeys.all })
      onDone()
    },
    onError: (e) => setError(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return setError("Give the portal a name.")
    if (!/^https?:\/\//i.test(url.trim()))
      return setError("The portal link must start with https://")
    setError(null)
    save.mutate({
      portal_name: name.trim(),
      portal_url: url.trim(),
      status,
      signed_in_runner: status === "signed_in" ? runner || null : null,
      email_used: email.trim() || null,
    })
  }

  return (
    <form
      onSubmit={submit}
      aria-label={account ? "Edit portal" : "Add a portal"}
      className="grid gap-3 panel p-4"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium">
          Portal name
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Kafue Analytics careers"
          />
        </label>
        <label className="grid gap-1 text-sm font-medium">
          Portal link
          <Input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://careers.example.com"
          />
        </label>
        <label className="grid gap-1 text-sm font-medium">
          Where you got to
          <NativeSelect
            value={status}
            onChange={(e) => setStatus(e.target.value as PortalAccountStatus)}
          >
            {(Object.keys(ACCOUNT_STATUS_LABEL) as PortalAccountStatus[]).map(
              (s) => (
                <option key={s} value={s}>
                  {ACCOUNT_STATUS_LABEL[s]}
                </option>
              )
            )}
          </NativeSelect>
        </label>
        {status === "signed_in" && (
          <label className="grid gap-1 text-sm font-medium">
            Signed in on
            <NativeSelect
              value={runner}
              onChange={(e) => setRunner(e.target.value)}
            >
              <option value="">Choose a runner</option>
              {runners.data?.map((r) => (
                <option key={r.token_id} value={r.name}>
                  {r.name}
                </option>
              ))}
            </NativeSelect>
          </label>
        )}
        <label className="grid gap-1 text-sm font-medium">
          Email used to register (optional)
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </label>
      </div>
      <p className="text-sm text-muted-foreground">
        Sign in yourself in your runner's browser. Passwords stay in that
        browser and are never kept here.
      </p>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Save portal
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
