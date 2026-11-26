import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Copy, KeyRound } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { NativeSelect } from "@/features/campaigns/bits"
import { errorText } from "@/features/autopilot/api"
import { createToken, tokenKeys, type RunnerKind, type Scope } from "./api"
import { KIND_LABEL, SCOPES } from "./logic"

/** The environment variable the runner reads its token from (see the setup guides). */
export const TOKEN_ENV = "NCHITO_RUNNER_TOKEN"

/** Scopes ticked at first: enough to do the job, no more. The owner can untick any. */
const STARTING_SCOPES: Scope[] = [
  "gateway:tasks",
  "gateway:packets",
  "gateway:permits",
]

/**
 * Creates a scoped gateway token. The secret lives only in this component's state: it is not
 * put in any query cache, and closing the dialog clears it. The server cannot show it again.
 */
export function CreateTokenDialog({
  defaultKind,
}: {
  defaultKind?: RunnerKind
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [kind, setKind] = useState<RunnerKind>(defaultKind ?? "pc")
  const [scopes, setScopes] = useState<Scope[]>(STARTING_SCOPES)
  const [secret, setSecret] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: createToken,
    onSuccess: (t) => {
      setSecret(t.token)
      void qc.invalidateQueries({ queryKey: tokenKeys.tokens })
      void qc.invalidateQueries({ queryKey: tokenKeys.runners })
    },
    onError: (e) => setError(errorText(e)),
  })

  const close = () => {
    setOpen(false)
    setSecret(null)
    setName("")
    setError(null)
    setScopes(STARTING_SCOPES)
    create.reset() // drops the secret from the mutation cache too
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return setError("Give the token a name.")
    if (scopes.length === 0) return setError("Allow at least one thing.")
    setError(null)
    create.mutate({ name: name.trim(), runner_kind: kind, scopes })
  }

  const copy = async () => {
    if (!secret) return
    try {
      await navigator.clipboard.writeText(secret)
      toast.success("Copied.")
    } catch {
      toast.error("Could not copy. Select the token and copy it by hand.")
    }
  }

  const toggle = (s: Scope) =>
    setScopes((cur) =>
      cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]
    )

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : close())}>
      <DialogTrigger asChild>
        <Button>
          <KeyRound aria-hidden="true" /> Create a token
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        {secret ? (
          <>
            <DialogHeader>
              <DialogTitle>Copy your token now</DialogTitle>
              <DialogDescription>
                You won't see this again. Only a short start of it is kept here.
                If you lose it, revoke it and create a new one.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-2">
              <code
                data-testid="token-secret"
                className="block rounded-md border border-border bg-sunken p-2.5 text-sm break-all select-all"
              >
                {secret}
              </code>
              <Button variant="outline" onClick={() => void copy()}>
                <Copy aria-hidden="true" /> Copy token
              </Button>
              <p className="text-sm text-muted-foreground">
                Put it in the environment variable <code>{TOKEN_ENV}</code> on
                the machine that runs the agent. Never paste it into a chat or a
                file you share.
              </p>
            </div>
            <DialogFooter>
              <Button onClick={close}>I've copied it</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="grid gap-3">
            <DialogHeader>
              <DialogTitle>Create a gateway token</DialogTitle>
              <DialogDescription>
                A runner uses this token to ask for work. It can do only what
                you allow below.
              </DialogDescription>
            </DialogHeader>
            <label className="grid gap-1 text-sm font-medium">
              Name
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Office PC"
                maxLength={120}
              />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Where it runs
              <NativeSelect
                value={kind}
                onChange={(e) => setKind(e.target.value as RunnerKind)}
              >
                <option value="pc">
                  {KIND_LABEL.pc} (Claude Code with Chrome)
                </option>
                <option value="server">{KIND_LABEL.server} (container)</option>
              </NativeSelect>
            </label>
            <fieldset className="grid gap-1.5">
              <legend className="mb-1 text-sm font-medium">It may</legend>
              {SCOPES.map((s) => (
                <label key={s.value} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={scopes.includes(s.value)}
                    onChange={() => toggle(s.value)}
                  />
                  <span>
                    {s.label}
                    <span className="block text-muted-foreground">
                      {s.hint}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button type="submit" disabled={create.isPending}>
                Create token
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
