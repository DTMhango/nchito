/** The fields of each typed-in connection, named as the server's config and secret keys. */
import type { ConnectionProvider } from "./api"

export type FieldDef = {
  name: string
  label: string
  /** "config" is stored in plain; "secret" is encrypted and never shown again. */
  to: "config" | "secret"
  type?: "text" | "number" | "email" | "url" | "password" | "select"
  /** For `select`: the values the server accepts. */
  options?: readonly string[]
  placeholder?: string
  help?: string
  optional?: boolean
  /** Shortest accepted value (the server checks it too). */
  minLength?: number
}

/** Mail security modes the server accepts. */
const SECURITY = ["ssl", "starttls", "none"] as const
/** The server refuses a shorter webhook signing secret. */
export const WEBHOOK_SECRET_MIN = 16

export const FORMS: Record<
  Exclude<ConnectionProvider, "gmail" | "gdrive">,
  { cta: string; fields: FieldDef[] }
> = {
  imap_smtp: {
    cta: "Connect mailbox",
    fields: [
      {
        name: "from_address",
        label: "Email address",
        to: "config",
        type: "email",
      },
      {
        name: "username",
        label: "Sign-in name",
        to: "config",
        optional: true,
        help: "Leave empty when it is the email address.",
      },
      {
        name: "imap_host",
        label: "IMAP server",
        to: "config",
        placeholder: "imap.example.com",
      },
      {
        name: "imap_port",
        label: "IMAP port",
        to: "config",
        type: "number",
        optional: true,
      },
      {
        name: "imap_security",
        label: "IMAP security",
        to: "config",
        type: "select",
        options: SECURITY,
        optional: true,
      },
      {
        name: "read_folder",
        label: "Folder to read",
        to: "config",
        optional: true,
        help: "The app reads only this folder. Leave empty to read nothing.",
      },
      {
        name: "sent_folder",
        label: "Sent folder",
        to: "config",
        placeholder: "Sent",
        optional: true,
      },
      {
        name: "smtp_host",
        label: "SMTP server",
        to: "config",
        placeholder: "smtp.example.com",
      },
      {
        name: "smtp_port",
        label: "SMTP port",
        to: "config",
        type: "number",
        optional: true,
      },
      {
        name: "smtp_security",
        label: "SMTP security",
        to: "config",
        type: "select",
        options: SECURITY,
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
      {
        name: "chat_id",
        label: "Chat ID",
        to: "config",
        help: "A number, or @channelname.",
      },
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
        minLength: WEBHOOK_SECRET_MIN,
        help: `At least ${WEBHOOK_SECRET_MIN} characters. Each message is signed with it so you can check it came from here. Encrypted and never shown again.`,
      },
    ],
  },
}
