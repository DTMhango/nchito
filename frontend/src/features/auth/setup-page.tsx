import { useMemo } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRouter } from "@tanstack/react-router"
import { Lock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { createOwner, keys, login, meQuery } from "@/lib/api/endpoints"
import { AuthLayout } from "./auth-layout"
import { PasswordInput } from "./password-input"

/** The owner's time zone default (DESIGN 16: Africa/Lusaka) unless the browser says otherwise. */
const DEFAULT_TZ = "Africa/Lusaka"

const schema = z
  .object({
    display_name: z
      .string()
      .trim()
      .min(1, "What should the app call you?")
      .max(60),
    email: z.email("Enter a valid email address."),
    password: z
      .string()
      .min(12, "Use at least 12 characters. A short sentence works well."),
    confirm: z.string(),
    timezone: z.string().min(1),
  })
  .refine((v) => v.password === v.confirm, {
    path: ["confirm"],
    message: "The two passwords don't match.",
  })
type Values = z.infer<typeof schema>

function timeZones(): string[] {
  try {
    const list = Intl.supportedValuesOf("timeZone")
    return list.includes(DEFAULT_TZ) ? list : [DEFAULT_TZ, ...list]
  } catch {
    return [DEFAULT_TZ, "UTC"]
  }
}

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_TZ
  } catch {
    return DEFAULT_TZ
  }
}

/** First run: create the one owner account. Step 1 of the set-up guide (DESIGN 13). */
export function SetupPage() {
  const qc = useQueryClient()
  const router = useRouter()
  const zones = useMemo(() => timeZones(), [])
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      display_name: "",
      email: "",
      password: "",
      confirm: "",
      timezone: browserZone(),
    },
  })

  const m = useMutation({
    mutationFn: async (v: Values) => {
      await createOwner({
        display_name: v.display_name.trim(),
        email: v.email.trim(),
        password: v.password,
        timezone: v.timezone,
      })
      // Sign in straight away, whether or not the server already started a session.
      await login({ email: v.email.trim(), password: v.password })
    },
    onSuccess: async () => {
      qc.removeQueries({ queryKey: keys.setup })
      qc.removeQueries({ queryKey: keys.me })
      await qc.fetchQuery(meQuery())
      await router.navigate({ to: "/onboarding", search: { step: 1 } })
    },
  })

  const errors = form.formState.errors
  return (
    <AuthLayout>
      <div className="mb-6 grid gap-1.5">
        <div className="eyebrow">First run · step 1 of 6</div>
        <h1 className="text-2xl">Set up your account</h1>
        <p className="text-muted-foreground">
          This instance belongs to one person. Create the owner account; nobody
          else can sign up after this.
        </p>
      </div>
      <form
        onSubmit={form.handleSubmit((v) => m.mutate(v))}
        noValidate
        className="grid gap-5"
      >
        <FieldGroup className="gap-4">
          <Field data-invalid={!!errors.display_name || undefined}>
            <FieldLabel htmlFor="display_name">Your first name</FieldLabel>
            <Input
              id="display_name"
              autoComplete="given-name"
              autoFocus
              aria-invalid={!!errors.display_name || undefined}
              {...form.register("display_name")}
            />
            {errors.display_name ? (
              <FieldError>{errors.display_name.message}</FieldError>
            ) : (
              <FieldDescription>
                Used in greetings, never on a CV.
              </FieldDescription>
            )}
          </Field>
          <Field data-invalid={!!errors.email || undefined}>
            <FieldLabel htmlFor="email">Email</FieldLabel>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              aria-invalid={!!errors.email || undefined}
              {...form.register("email")}
            />
            {errors.email ? (
              <FieldError>{errors.email.message}</FieldError>
            ) : (
              <FieldDescription>
                For signing in. It doesn't have to be the address you apply
                from.
              </FieldDescription>
            )}
          </Field>
          <Field data-invalid={!!errors.password || undefined}>
            <FieldLabel htmlFor="password">Password</FieldLabel>
            <PasswordInput
              id="password"
              autoComplete="new-password"
              aria-invalid={!!errors.password || undefined}
              {...form.register("password")}
            />
            {errors.password ? (
              <FieldError>{errors.password.message}</FieldError>
            ) : (
              <FieldDescription>At least 12 characters.</FieldDescription>
            )}
          </Field>
          <Field data-invalid={!!errors.confirm || undefined}>
            <FieldLabel htmlFor="confirm">Password again</FieldLabel>
            <PasswordInput
              id="confirm"
              autoComplete="new-password"
              aria-invalid={!!errors.confirm || undefined}
              {...form.register("confirm")}
            />
            {errors.confirm && (
              <FieldError>{errors.confirm.message}</FieldError>
            )}
          </Field>
          <Field>
            <FieldLabel htmlFor="timezone">Time zone</FieldLabel>
            <select
              id="timezone"
              className="h-8 w-full rounded-md border field-focus border-input bg-surface px-2 text-base text-foreground"
              {...form.register("timezone")}
            >
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z.replace(/_/g, " ")}
                </option>
              ))}
            </select>
            <FieldDescription>
              Schedules, quiet hours and deadlines show in this zone.
            </FieldDescription>
          </Field>
        </FieldGroup>

        {m.error && (
          <p
            role="alert"
            className="rounded-sm bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {m.error.message}
          </p>
        )}

        <Button type="submit" size="lg" disabled={m.isPending}>
          {m.isPending
            ? "Creating your account…"
            : "Create account and continue"}
        </Button>
        <p className="flex items-start gap-2 text-xs text-faint">
          <Lock className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          Your password is hashed on the server. You can add two-step sign-in
          later under Settings, Security.
        </p>
      </form>
    </AuthLayout>
  )
}
