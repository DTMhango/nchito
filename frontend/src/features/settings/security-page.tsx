import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Chip } from "@/components/chip"
import { PageHeader, SectionHeader } from "@/components/page-header"
import { meQuery, keys } from "@/lib/api/endpoints"
import { useSignOut } from "@/features/auth/use-sign-out"
import {
  changePassword,
  totpDisable,
  totpEnable,
  totpSetup,
} from "./api"

const MIN_PASSWORD = 12

function errorText(e: unknown) {
  return e instanceof Error ? e.message : "Something went wrong."
}

function PasswordForm() {
  const [current, setCurrent] = useState("")
  const [next, setNext] = useState("")
  const [again, setAgain] = useState("")
  const [error, setError] = useState<string | null>(null)
  const change = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: () => {
      setCurrent("")
      setNext("")
      setAgain("")
      toast.success("Password changed")
    },
    onError: (e) => setError(errorText(e)),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (next.length < MIN_PASSWORD)
      return setError(`Use at least ${MIN_PASSWORD} characters.`)
    if (next !== again) return setError("The two new passwords don't match.")
    setError(null)
    change.mutate()
  }
  return (
    <form onSubmit={submit} className="grid max-w-[420px] gap-3" aria-label="Change password">
      <label className="grid gap-1 text-sm">
        Current password
        <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      </label>
      <label className="grid gap-1 text-sm">
        New password
        <Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      <label className="grid gap-1 text-sm">
        New password again
        <Input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
      </label>
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <Button type="submit" className="justify-self-start" disabled={change.isPending || !current}>
        Change password
      </Button>
    </form>
  )
}

function TwoStep({ enabled }: { enabled: boolean }) {
  const qc = useQueryClient()
  const [code, setCode] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const refreshMe = () => qc.invalidateQueries({ queryKey: keys.me })

  const setup = useMutation({ mutationFn: totpSetup, onError: (e) => setError(errorText(e)) })
  const enable = useMutation({
    mutationFn: () => totpEnable(code),
    onSuccess: () => {
      setCode("")
      setup.reset()
      toast.success("Two-step sign-in is on")
      void refreshMe()
    },
    onError: (e) => setError(errorText(e)),
  })
  const disable = useMutation({
    mutationFn: () => totpDisable(password, code),
    onSuccess: () => {
      setCode("")
      setPassword("")
      toast.success("Two-step sign-in is off")
      void refreshMe()
    },
    onError: (e) => setError(errorText(e)),
  })

  if (enabled) {
    return (
      <form
        aria-label="Turn off two-step sign-in"
        className="grid max-w-[420px] gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          setError(null)
          disable.mutate()
        }}
      >
        <p className="text-sm text-muted-foreground">
          To turn it off, confirm with your password and a current code.
        </p>
        <label className="grid gap-1 text-sm">
          Password
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="grid gap-1 text-sm">
          Authenticator code
          <Input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <Button type="submit" variant="destructive" className="justify-self-start" disabled={!password || !code || disable.isPending}>
          Turn off
        </Button>
      </form>
    )
  }
  if (!setup.data) {
    return (
      <div className="grid gap-2">
        <p className="text-sm text-muted-foreground">
          Add an authenticator app (any TOTP app) so sign-in needs a six-digit code as well as your password.
        </p>
        <Button className="justify-self-start" onClick={() => setup.mutate()} disabled={setup.isPending}>
          Set up an authenticator code
        </Button>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      </div>
    )
  }
  return (
    <form
      aria-label="Confirm authenticator code"
      className="grid max-w-[420px] gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        setError(null)
        enable.mutate()
      }}
    >
      <p className="text-sm">
        In your authenticator app, add an account by entering this key, or open
        the link on the phone that has the app.
      </p>
      <code className="num rounded-sm bg-sunken p-2.5 text-sm break-all select-all">
        {setup.data.secret}
      </code>
      <a className="text-sm text-primary-ink underline" href={setup.data.otpauth_uri}>
        Open in authenticator app
      </a>
      <label className="grid gap-1 text-sm">
        Code from the app
        <Input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
      </label>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <Button type="submit" className="justify-self-start" disabled={code.length < 6 || enable.isPending}>
        Turn on
      </Button>
    </form>
  )
}

/** Settings, Security: password, two-step sign-in and the sessions you are signed in on. */
export function SecurityPage() {
  const me = useQuery(meQuery())
  const signOut = useSignOut()
  const twoStep = (me.data as { totp_enabled?: boolean } | null | undefined)?.totp_enabled === true
  return (
    <div className="grid gap-7">
      <PageHeader title="Security" description="Your password, two-step sign-in and where you are signed in." />
      <section aria-label="Password" className="panel p-4">
        <SectionHeader title="Password" aside="At least 12 characters" />
        <PasswordForm />
      </section>
      <section aria-label="Two-step sign-in" className="panel p-4">
        <SectionHeader
          title="Two-step sign-in"
          action={
            <Chip tone={twoStep ? "good" : "neutral"}>
              {twoStep ? "On" : "Off"}
            </Chip>
          }
        />
        <TwoStep enabled={twoStep} />
      </section>
      <section aria-label="Sessions" className="panel p-4">
        <SectionHeader title="Sessions" />
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <b>This browser</b> <Chip tone="good">Current</Chip>
            <p className="text-sm text-muted-foreground">
              Signed in as {me.data?.email ?? "you"}. A list of other devices will
              appear here once the server reports them.
            </p>
          </div>
          <Button variant="outline" size="sm" className="ml-auto" onClick={() => signOut()}>
            Sign out
          </Button>
        </div>
      </section>
    </div>
  )
}
