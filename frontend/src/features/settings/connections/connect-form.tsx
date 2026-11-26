import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { isApiError } from "@/lib/api/client"
import {
  connectionKeys,
  createConnection,
  oauthStart,
  updateConnection,
  type Connection,
  type OAuthProvider,
} from "./api"
import { FORMS, type FieldDef } from "./forms"

/**
 * Add a connection from a short form, or change one (`existing`). Secret fields always start
 * empty and are cleared after saving; when changing, an empty secret keeps the saved one.
 */
export function ConnectForm({
  provider,
  label,
  existing,
  onDone,
}: {
  provider: keyof typeof FORMS
  label: string
  existing?: Connection
  onDone?: () => void
}) {
  const qc = useQueryClient()
  const uid = useId()
  const { fields, cta, check } = FORMS[provider]
  const initial = () =>
    Object.fromEntries(
      fields
        .filter((f) => f.to === "config" && existing?.config[f.name] != null)
        .map((f) => [f.name, String(existing?.config[f.name])])
    )
  const [values, setValues] = useState<Record<string, string>>(initial)
  const save = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = {}
      const secrets: Record<string, string> = {}
      for (const f of fields) {
        const v = (values[f.name] ?? "").trim()
        if (!v) continue
        if (f.to === "secret") secrets[f.name] = values[f.name]
        else config[f.name] = f.type === "number" ? Number(v) : v
      }
      return existing
        ? updateConnection(existing.id, { config, secrets })
        : createConnection({ provider, label, config, secrets })
    },
    onSuccess: () => {
      setValues(existing ? initial() : {})
      void qc.invalidateQueries({ queryKey: connectionKeys.all })
      onDone?.()
    },
  })
  // When changing, a secret may stay empty: the saved one is kept.
  const required = (f: FieldDef) =>
    !f.optional && !(existing && f.to === "secret")
  const missing = fields.some((f) => required(f) && !values[f.name]?.trim())
  const tooShort = fields.find((f) => {
    const n = (values[f.name] ?? "").length
    return f.minLength !== undefined && n > 0 && n < f.minLength
  })
  const conflict = check?.(values) ?? null
  return (
    <form
      aria-label={existing ? `Change ${existing.label}` : `Add ${label}`}
      className="grid max-w-[520px] gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!missing && !tooShort && !conflict) save.mutate()
      }}
    >
      {fields.map((f) => (
        <div key={f.name} className="grid gap-1">
          <label htmlFor={`${uid}-${f.name}`} className="font-semibold">
            {f.label}
            {!required(f) && (
              <span className="font-normal text-muted-foreground">
                {existing && f.to === "secret"
                  ? " (leave empty to keep the saved one)"
                  : " (optional)"}
              </span>
            )}
          </label>
          {f.type === "select" ? (
            <select
              id={`${uid}-${f.name}`}
              value={values[f.name] ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, [f.name]: e.target.value }))
              }
              className="h-9 rounded-md border field-focus border-input bg-surface px-2 text-base"
            >
              <option value="">Server default</option>
              {f.options?.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <Input
              id={`${uid}-${f.name}`}
              type={f.type ?? "text"}
              autoComplete={f.type === "password" ? "new-password" : "off"}
              placeholder={f.placeholder}
              value={values[f.name] ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, [f.name]: e.target.value }))
              }
            />
          )}
          {f.help && <p className="text-sm text-muted-foreground">{f.help}</p>}
        </div>
      ))}
      {tooShort && (
        <p role="alert" className="text-sm text-danger">
          {tooShort.label} must be at least {tooShort.minLength} characters.
        </p>
      )}
      {conflict && (
        <p role="alert" className="text-sm text-danger">
          {conflict}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={missing || !!tooShort || !!conflict || save.isPending}
        >
          {existing ? "Save changes" : cta}
        </Button>
        {existing && onDone && (
          <Button type="button" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        )}
      </div>
      {save.isError && (
        <p role="alert" className="text-sm text-danger">
          {save.error.message}
        </p>
      )}
    </form>
  )
}

/** Shown when the server has no Google OAuth client (start answers 409). */
export const GOOGLE_NOT_SET_UP =
  "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET on the server to connect Google."

/** Shown when the server has no Microsoft Entra app (start answers 409). */
export const MICROSOFT_NOT_SET_UP =
  "Set MS_OAUTH_CLIENT_ID and MS_OAUTH_CLIENT_SECRET on the server to connect Microsoft."

/** Gmail, Drive, Outlook and OneDrive sign in at the provider, so there is nothing to type here. */
export function OAuthButton({
  provider,
  label,
}: {
  provider: OAuthProvider
  label: string
}) {
  const start = useMutation({
    mutationFn: () => oauthStart(provider),
    onSuccess: ({ authorize_url }) => {
      if (/^https:\/\//.test(authorize_url))
        window.location.assign(authorize_url)
    },
  })
  return (
    <div className="grid gap-2">
      <div>
        <Button onClick={() => start.mutate()} disabled={start.isPending}>
          {label}
        </Button>
      </div>
      {start.isError && (
        <p role="alert" className="text-sm text-danger">
          {isApiError(start.error, 409)
            ? provider === "msgraph" || provider === "onedrive"
              ? MICROSOFT_NOT_SET_UP
              : GOOGLE_NOT_SET_UP
            : start.error.message}
        </p>
      )}
    </div>
  )
}
