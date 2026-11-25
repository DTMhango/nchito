import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRouter } from "@tanstack/react-router"
import { KeyRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { keys, login, meQuery } from "@/lib/api/endpoints"
import { isApiError } from "@/lib/api/client"
import { safeRedirect } from "@/app/guard"
import { AuthLayout } from "./auth-layout"
import { PasswordInput } from "./password-input"

const schema = z.object({
  email: z.email("Enter the email you set up with."),
  password: z.string().min(1, "Enter your password."),
  totp: z
    .string()
    .trim()
    .refine((v) => v === "" || /^\d{6}$/.test(v), "Codes are 6 digits."),
})
type Values = z.infer<typeof schema>

const MOCK = import.meta.env.VITE_MOCK === "1"

export function SignInPage({ redirectTo }: { redirectTo?: string }) {
  const qc = useQueryClient()
  const router = useRouter()
  const [showTotp, setShowTotp] = useState(false)
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "", totp: "" },
  })

  const m = useMutation({
    mutationFn: (v: Values) =>
      login({
        email: v.email.trim(),
        password: v.password,
        ...(v.totp ? { totp: v.totp } : {}),
      }),
    onSuccess: async () => {
      qc.removeQueries({ queryKey: keys.me })
      await qc.fetchQuery(meQuery())
      await router.navigate({ href: safeRedirect(redirectTo) })
    },
    onError: (e) => {
      if (isApiError(e, 401) && /code|totp|two.?factor/i.test(e.message))
        setShowTotp(true)
    },
  })

  const errors = form.formState.errors
  const serverError = m.error
    ? isApiError(m.error, 401)
      ? m.error.message || "That email and password don't match."
      : m.error.message
    : null

  return (
    <AuthLayout>
      <div className="mb-6 grid gap-1.5">
        <h1 className="text-2xl">Sign in</h1>
        <p className="text-muted-foreground">
          Welcome back. Your hunt carried on while you were away.
        </p>
      </div>
      <form
        onSubmit={form.handleSubmit((v) => m.mutate(v))}
        noValidate
        className="grid gap-5"
      >
        <FieldGroup className="gap-4">
          <Field data-invalid={!!errors.email || undefined}>
            <FieldLabel htmlFor="email">Email</FieldLabel>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              autoFocus
              aria-invalid={!!errors.email || undefined}
              {...form.register("email")}
            />
            {errors.email && <FieldError>{errors.email.message}</FieldError>}
          </Field>
          <Field data-invalid={!!errors.password || undefined}>
            <FieldLabel htmlFor="password">Password</FieldLabel>
            <PasswordInput
              id="password"
              autoComplete="current-password"
              aria-invalid={!!errors.password || undefined}
              {...form.register("password")}
            />
            {errors.password && (
              <FieldError>{errors.password.message}</FieldError>
            )}
          </Field>
          {showTotp ? (
            <Field data-invalid={!!errors.totp || undefined}>
              <FieldLabel htmlFor="totp">Authenticator code</FieldLabel>
              <Input
                id="totp"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="6 digits"
                className="num tracking-[0.3em]"
                aria-invalid={!!errors.totp || undefined}
                {...form.register("totp")}
              />
              {errors.totp ? (
                <FieldError>{errors.totp.message}</FieldError>
              ) : (
                <FieldDescription>
                  Only needed if you turned on two-step sign-in.
                </FieldDescription>
              )}
            </Field>
          ) : (
            <button
              type="button"
              onClick={() => setShowTotp(true)}
              className="flex items-center gap-1.5 justify-self-start text-sm text-primary-ink hover:underline"
            >
              <KeyRound className="size-3.5" aria-hidden="true" />I use an
              authenticator code
            </button>
          )}
        </FieldGroup>

        {serverError && (
          <p
            role="alert"
            className="rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {serverError}
          </p>
        )}

        <Button type="submit" size="lg" disabled={m.isPending}>
          {m.isPending ? "Signing in…" : "Sign in"}
        </Button>

        {MOCK && (
          <div className="grid gap-2 rounded-sm border border-dashed border-border-strong p-3 text-sm text-muted-foreground">
            <span>
              Mock backend. Sign in as{" "}
              <span className="num">owner@example.com</span> with{" "}
              <span className="num">demo-password</span>.
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="justify-self-start"
              onClick={() => {
                form.setValue("email", "owner@example.com")
                form.setValue("password", "demo-password")
              }}
            >
              Fill in the demo account
            </Button>
          </div>
        )}
      </form>
    </AuthLayout>
  )
}
