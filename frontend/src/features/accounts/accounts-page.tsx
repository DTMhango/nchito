import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Plus, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Chip, type ChipTone } from "@/components/chip"
import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { View } from "@/components/view"
import { NativeSelect } from "@/features/campaigns/bits"
import { errorText, runnersQuery } from "@/features/autopilot/api"
import {
  accountKeys,
  accountsQuery,
  createAccount,
  deleteAccount,
  refreshAccounts,
  updateAccount,
  type PortalAccount,
  type PortalAccountStatus,
} from "./api"
import {
  ACCOUNT_STATUS_LABEL,
  accountName,
  accountStatusText,
  dateText,
} from "./logic"

const TONE: Record<PortalAccountStatus, ChipTone> = {
  none: "neutral",
  created: "info",
  signed_in: "good",
}
const STATUSES = Object.keys(ACCOUNT_STATUS_LABEL) as PortalAccountStatus[]

/** Portal accounts: one row per portal tenant. The email used is kept; a password never is. */
export function AccountsPage() {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<PortalAccountStatus | null>(null)
  const q = useQuery(accountsQuery(filter))
  const [editing, setEditing] = useState<PortalAccount | "new" | null>(null)
  const refresh = useMutation({
    mutationFn: refreshAccounts,
    onSuccess: (r) => {
      toast.success(
        `Checked: ${r.raised} new sign-in request${r.raised === 1 ? "" : "s"}, ${r.closed} closed, ${r.reminded} reminder${r.reminded === 1 ? "" : "s"} sent.`
      )
      void qc.invalidateQueries({ queryKey: accountKeys.all })
      void qc.invalidateQueries({ queryKey: ["pending-actions"] })
    },
    onError: (e) => toast.error(errorText(e)),
  })
  return (
    <View className="grid content-start gap-5">
      <PageHeader
        title="Portal accounts"
        description="Employer portals that need an account. You create the account and sign in yourself, in the browser your runner uses. This list only keeps track of where you got to. No passwords are stored or asked for here."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={refresh.isPending}
              onClick={() => refresh.mutate()}
            >
              <RefreshCw aria-hidden="true" /> Check now
            </Button>
            <Button onClick={() => setEditing("new")}>
              <Plus aria-hidden="true" /> Add a portal
            </Button>
          </div>
        }
      />
      <label className="flex max-w-xs items-center gap-2 text-sm">
        Show
        <NativeSelect
          aria-label="Show accounts"
          value={filter ?? ""}
          onChange={(e) =>
            setFilter((e.target.value || null) as PortalAccountStatus | null)
          }
        >
          <option value="">Every account</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {ACCOUNT_STATUS_LABEL[s]}
            </option>
          ))}
        </NativeSelect>
      </label>
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
          title="No portals here"
          description="A portal appears here when a role needs an account, or you can add one."
        />
      )}
      {q.isSuccess && q.data.length > 0 && (
        <ul aria-label="Portal accounts" className="grid gap-2.5">
          {q.data.map((a) => (
            <AccountRow key={a.id} account={a} onEdit={() => setEditing(a)} />
          ))}
        </ul>
      )}
    </View>
  )
}

function AccountRow({
  account: a,
  onEdit,
}: {
  account: PortalAccount
  onEdit: () => void
}) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const remove = useMutation({
    mutationFn: () => deleteAccount(a.id),
    onSuccess: () => {
      toast.success("Portal removed from the list.")
      void qc.invalidateQueries({ queryKey: accountKeys.all })
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const name = accountName(a)
  return (
    <li
      aria-label={name}
      className="grid gap-1.5 rounded-lg border border-border bg-surface p-3.5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-md">{name}</h3>
        <Chip tone={TONE[a.status]}>{accountStatusText(a)}</Chip>
        {a.waiting_applications > 0 && (
          <Chip tone="warn">
            {a.waiting_applications} application
            {a.waiting_applications === 1 ? "" : "s"} waiting
          </Chip>
        )}
        <div className="ml-auto flex gap-1">
          {a.open_action_id && (
            <Button asChild variant="outline" size="sm">
              <Link
                to="/accounts/handoff/$actionId"
                params={{ actionId: a.open_action_id }}
              >
                Sign-in request
              </Link>
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Edit ${name}`}
            onClick={onEdit}
          >
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Remove ${name}`}
            onClick={() => setConfirming(true)}
          >
            Remove
          </Button>
        </div>
      </div>
      {a.url && (
        <p className="text-sm text-muted-foreground">
          <a
            href={a.url}
            target="_blank"
            rel="noreferrer noopener"
            className="underline underline-offset-2"
          >
            {a.url}
          </a>
        </p>
      )}
      <p className="text-sm text-faint">
        Email used: {a.email_used ?? "not recorded"} · Last sign-in:{" "}
        {dateText(a.last_sign_in_at)}
      </p>
      {a.notes && <p className="text-sm text-muted-foreground">{a.notes}</p>}
      {confirming && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>
            Remove {name} from this list? Your account at the portal is not
            touched.
          </span>
          <Button
            size="sm"
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Yes, remove
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setConfirming(false)}
          >
            Keep it
          </Button>
        </div>
      )}
    </li>
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
  const [portal, setPortal] = useState(account?.portal ?? "")
  const [tenant, setTenant] = useState(account?.tenant ?? "")
  const [url, setUrl] = useState(account?.url ?? "")
  const [status, setStatus] = useState<PortalAccountStatus>(
    account?.status ?? "none"
  )
  const [runner, setRunner] = useState(account?.signed_in_runner ?? "")
  const [email, setEmail] = useState(account?.email_used ?? "")
  const [notes, setNotes] = useState(account?.notes ?? "")
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () => {
      const common = {
        url: url.trim() || null,
        status,
        signed_in_runner: status === "signed_in" ? runner || null : null,
        email_used: email.trim() || null,
        notes: notes.trim() || null,
      }
      return account
        ? updateAccount(account.id, common)
        : createAccount({
            portal: portal.trim(),
            tenant: tenant.trim(),
            ...common,
          })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: accountKeys.all })
      onDone()
    },
    onError: (e) => setError(errorText(e)),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!account && !portal.trim())
      return setError("Say which portal system it is, for example workday.")
    if (!account && !tenant.trim())
      return setError(
        "Give the portal's address, for example careers.example.com."
      )
    if (url.trim() && !/^https?:\/\//i.test(url.trim()))
      return setError("The portal link must start with https://")
    if (status === "signed_in" && !runner)
      return setError("Say which runner holds the session.")
    setError(null)
    save.mutate()
  }

  const runnerNames = runners.data?.map((r) => r.name) ?? []
  if (runner && !runnerNames.includes(runner)) runnerNames.push(runner)

  return (
    <form
      onSubmit={submit}
      aria-label={account ? "Edit portal" : "Add a portal"}
      className="grid gap-3 panel p-4"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium">
          Portal system
          <Input
            value={portal}
            disabled={!!account}
            onChange={(e) => setPortal(e.target.value)}
            placeholder="workday"
          />
        </label>
        <label className="grid gap-1 text-sm font-medium">
          Portal address
          <Input
            value={tenant}
            disabled={!!account}
            onChange={(e) => setTenant(e.target.value)}
            placeholder="careers.example.com"
          />
        </label>
        <label className="grid gap-1 text-sm font-medium">
          Portal link (optional)
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
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {ACCOUNT_STATUS_LABEL[s]}
              </option>
            ))}
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
              {runnerNames.map((n) => (
                <option key={n} value={n}>
                  {n}
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
        <label className="grid gap-1 text-sm font-medium sm:col-span-2">
          Notes (optional)
          <Input value={notes} onChange={(e) => setNotes(e.target.value)} />
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
