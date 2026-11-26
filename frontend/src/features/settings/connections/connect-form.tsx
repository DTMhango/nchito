import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  connectionKeys,
  createConnection,
  oauthStart,
  type ConnectionProvider,
} from "./api"

export type FieldDef = {
  name: string
  label: string
  /** "config" is stored in plain; "secret" is encrypted and never shown again. */
  to: "config" | "secret"
  type?: "text" | "number" | "email" | "url" | "password"
  placeholder?: string
  help?: string
  optional?: boolean
}

export const FORMS: Record<
  Exclude<ConnectionProvider, "gmail" | "gdrive">,
  { cta: string; fields: FieldDef[] }
> = {
  imap_smtp: {
    cta: "Connect mailbox",
    fields: [
      { name: "email", label: "Email address", to: "config", type: "email" },
      {
        name: "imap_host",
        label: "IMAP server",
        to: "config",
        placeholder: "imap.example.com",
      },
      { name: "imap_port", label: "IMAP port", to: "config", type: "number" },
      {
        name: "smtp_host",
        label: "SMTP server",
        to: "config",
        placeholder: "smtp.example.com",
      },
      { name: "smtp_port", label: "SMTP port", to: "config", type: "number" },
      {
        name: "read_query",
        label: "Folder or label to read",
        to: "config",
        help: "The app reads only this folder. Leave empty to read nothing.",
        optional: true,
      },
      {
        name: "password",
        label: "App password",
        to: "secret",
        type: "password",
        help: "Use an app password, not your main password. It is encrypted and never shown again.",
      },
    ],
  },
  telegram: {
    cta: "Connect Telegram bot",
    fields: [
      { name: "chat_id", label: "Chat ID", to: "config" },
      {
        name: "bot_token",
        label: "Bot token",
        to: "secret",
        type: "password",
        help: "From @BotFather. Encrypted and never shown again.",
      },
    ],
  },
  webhook: {
    cta: "Connect webhook",
    fields: [
      {
        name: "url",
        label: "Webhook address",
        to: "config",
        type: "url",
        placeholder: "https://example.com/hook",
      },
      {
        name: "signing_secret",
        label: "Signing secret",
        to: "secret",
        type: "password",
        optional: true,
        help: "Used to sign each message so you can check it came from here. Encrypted and never shown again.",
      },
    ],
  },
}

/** Add a connection from a short form. Secret fields start empty and are cleared after saving. */
export function ConnectForm({
  provider,
  label,
}: {
  provider: keyof typeof FORMS
  label: string
}) {
  const qc = useQueryClient()
  const uid = useId()
  const { fields, cta } = FORMS[provider]
  const [values, setValues] = useState<Record<string, string>>({})
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
      return createConnection({ provider, label, config, secrets })
    },
    onSuccess: () => {
      setValues({})
      void qc.invalidateQueries({ queryKey: connectionKeys.all })
    },
  })
  const missing = fields.some((f) => !f.optional && !values[f.name]?.trim())
  return (
    <form
      aria-label={`Add ${label}`}
      className="grid max-w-[520px] gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!missing) save.mutate()
      }}
    >
      {fields.map((f) => (
        <div key={f.name} className="grid gap-1">
          <label htmlFor={`${uid}-${f.name}`} className="font-semibold">
            {f.label}
            {f.optional && (
              <span className="font-normal text-muted-foreground">
                {" "}
                (optional)
              </span>
            )}
          </label>
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
          {f.help && <p className="text-sm text-muted-foreground">{f.help}</p>}
        </div>
      ))}
      <div>
        <Button type="submit" disabled={missing || save.isPending}>
          {cta}
        </Button>
      </div>
      {save.isError && (
        <p role="alert" className="text-sm text-danger">
          {save.error.message}
        </p>
      )}
    </form>
  )
}

/** Gmail and Drive sign in at Google, so there is nothing to type here. */
export function OAuthButton({
  provider,
  label,
}: {
  provider: "gmail" | "gdrive"
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
          {start.error.message}
        </p>
      )}
    </div>
  )
}
