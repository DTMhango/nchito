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

export type FormDef = {
  cta: string
  fields: FieldDef[]
  /** A cross-field check the server also makes; returns the problem in plain words. */
  check?: (values: Record<string, string>) => string | null
}

/** The search provider takes its key in a header or in a query parameter, never both. */
export const checkSearchApi = (v: Record<string, string>) =>
  v.key_header?.trim() && v.key_param?.trim()
    ? "Give the key as a header or as a query parameter, not both."
    : null

export const FORMS: Record<
  Exclude<ConnectionProvider, "gmail" | "gdrive" | "onedrive">,
  FormDef
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
  msgraph: {
    // Outlook is added with Microsoft sign-in; this form only changes the folder it may read.
    cta: "Save",
    fields: [
      {
        name: "read_folder",
        label: "Folder to read",
        to: "config",
        optional: true,
        placeholder: "Inbox",
        help: "The app reads only this folder (Inbox, Archive, or the name of one of your folders). Leave empty to read nothing. Outlook cannot limit the permission itself to one folder.",
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
  search_api: {
    cta: "Connect search API",
    check: checkSearchApi,
    fields: [
      {
        name: "endpoint",
        label: "Search address",
        to: "config",
        type: "url",
        placeholder: "https://search.example.com/v1/search",
        help: "Where searches are sent (a GET request that answers in JSON).",
      },
      {
        name: "api_key",
        label: "API key",
        to: "secret",
        type: "password",
        help: "Encrypted and never shown again; only a masked end of it is shown.",
      },
      {
        name: "key_header",
        label: "Key header",
        to: "config",
        optional: true,
        placeholder: "X-API-Key",
        help: "The request header the key goes in. Use this or the key parameter, not both.",
      },
      {
        name: "key_param",
        label: "Key parameter",
        to: "config",
        optional: true,
        help: "The query parameter the key goes in, when the provider wants it in the address.",
      },
      {
        name: "query_param",
        label: "Search phrase parameter",
        to: "config",
        optional: true,
        help: "The query parameter that carries the search phrase. Empty: the server default.",
      },
      {
        name: "limit_param",
        label: "Result count parameter",
        to: "config",
        optional: true,
        help: "The query parameter for how many results to return. Empty when the provider has none.",
      },
      {
        name: "result_path",
        label: "Result list path",
        to: "config",
        optional: true,
        placeholder: "data.items",
        help: "Dotted path to the list of results in the answer. Empty: the server default.",
      },
      {
        name: "url_field",
        label: "Link field",
        to: "config",
        optional: true,
        help: "The field of one result that holds its link. Empty: the server default.",
      },
      {
        name: "title_field",
        label: "Title field",
        to: "config",
        optional: true,
        help: "The field of one result that holds its title. Empty: the server default.",
      },
    ],
  },
}
