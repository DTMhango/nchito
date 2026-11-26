import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Chip } from "@/components/chip"
import { SectionHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { errorText } from "@/features/autopilot/api"
import { revokeToken, tokenKeys, tokensQuery, type Token } from "./api"
import { KIND_LABEL, scopeLabel, tokenState } from "./logic"
import { CreateTokenDialog } from "./token-dialog"

const used = (iso: string | null) =>
  iso
    ? `Last used ${new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`
    : "Never used"

/** Tokens: only the first few characters are ever shown. The full secret was shown once, at creation. */
export function TokensSection() {
  const q = useQuery(tokensQuery())
  return (
    <section aria-labelledby="tokens-h" className="grid gap-3">
      <SectionHeader
        as="h3"
        title={<span id="tokens-h">Tokens</span>}
        aside="A runner proves who it is with a token. Revoke one and that runner stops at once."
        action={<CreateTokenDialog />}
      />
      {q.isSuccess && q.data.length === 0 && (
        <p className="text-sm text-muted-foreground">No tokens yet.</p>
      )}
      {q.isError && (
        <p role="alert" className="text-sm text-danger">
          Could not load tokens. Reload to try again.
        </p>
      )}
      <ul aria-label="Tokens" className="grid gap-2">
        {q.data?.map((t) => (
          <TokenRow key={t.id} token={t} />
        ))}
      </ul>
    </section>
  )
}

function TokenRow({ token: t }: { token: Token }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const state = tokenState(t)
  const revoke = useMutation({
    mutationFn: () => revokeToken(t.id),
    onSuccess: () => {
      toast.success("Token revoked.")
      setConfirming(false)
      void qc.invalidateQueries({ queryKey: tokenKeys.tokens })
      void qc.invalidateQueries({ queryKey: tokenKeys.runners })
    },
    onError: (e) => toast.error(errorText(e)),
  })
  return (
    <li
      aria-label={t.name}
      className="grid gap-1 rounded-lg border border-border bg-surface p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t.name}</span>
        <Chip tone="line">{KIND_LABEL[t.runner_kind]}</Chip>
        <Chip
          tone={
            state === "active"
              ? "good"
              : state === "paused"
                ? "warn"
                : "neutral"
          }
        >
          {state === "active"
            ? "Active"
            : state === "paused"
              ? "Paused"
              : "Revoked"}
        </Chip>
        <code className="text-sm text-faint">{t.prefix}…</code>
        <span className="ml-auto text-sm text-faint">
          {used(t.last_used_at)}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        May: {t.scopes.length ? t.scopes.map(scopeLabel).join(", ") : "nothing"}
      </p>
      {state !== "revoked" &&
        (confirming ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>
              Revoke {t.name}? It can never be used again. You would need a new
              token.
            </span>
            <Button
              size="sm"
              variant="destructive"
              disabled={revoke.isPending}
              onClick={() => revoke.mutate()}
            >
              Yes, revoke
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConfirming(false)}
            >
              Keep it
            </Button>
          </div>
        ) : (
          <div>
            <Button
              size="sm"
              variant="outline"
              aria-label={`Revoke ${t.name}`}
              onClick={() => setConfirming(true)}
            >
              Revoke
            </Button>
          </div>
        ))}
    </li>
  )
}
