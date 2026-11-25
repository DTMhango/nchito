import { Outlet } from "@tanstack/react-router"
import {
  Archive,
  Bell,
  Bot,
  Cable,
  Coins,
  Cpu,
  Database,
  FileClock,
  HardDrive,
  History,
  KeyRound,
  Lock,
  Mail,
  MessageCircle,
  RotateCcw,
  ScrollText,
  ShieldCheck,
  Undo2,
  type LucideIcon,
} from "lucide-react"
import { ScreenEmpty, type WhatAppears } from "@/components/empty-state"
import { SideNavLink, SubNav, SubNavLink } from "@/components/sub-nav"
import { View } from "@/components/view"
import { SETTINGS_SECTIONS } from "@/app/shell/nav"

/** Settings frame: section list on the left (tabs on phones), section on the right. */
export function SettingsLayout() {
  return (
    <View>
      <SubNav label="Settings sections" className="mb-5 md:hidden">
        {SETTINGS_SECTIONS.map((s) => (
          <SubNavLink key={s.to} to={s.to}>
            {s.label}
          </SubNavLink>
        ))}
      </SubNav>
      <div className="grid items-start gap-8 md:grid-cols-[200px_minmax(0,1fr)]">
        <nav
          aria-label="Settings sections"
          className="sticky top-0 hidden flex-col gap-0.5 md:flex"
        >
          {SETTINGS_SECTIONS.map((s) => (
            <SideNavLink key={s.to} to={s.to}>
              {s.label}
            </SideNavLink>
          ))}
        </nav>
        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </View>
  )
}

type Section = {
  icon: LucideIcon
  title: string
  lead: string
  items: WhatAppears[]
}

export const SETTINGS_EMPTY: Record<
  | "ai"
  | "connections"
  | "notifications"
  | "runners"
  | "data"
  | "security"
  | "activity"
  | "history",
  Section
> = {
  ai: {
    icon: Cpu,
    title: "AI",
    lead: "Providers, the model used at each stage, and budgets. Nothing paid runs until a monthly cap is set.",
    items: [
      {
        icon: KeyRound,
        title: "Providers",
        body: "Anthropic API by default; an OpenAI-compatible endpoint for OpenRouter or your own model.",
      },
      {
        icon: Cpu,
        title: "Model per stage",
        body: "Extraction and scoring on a small model, tailoring on a stronger one. Each route is tested before it is used.",
      },
      {
        icon: Coins,
        title: "Budgets",
        body: "Monthly cap, per-run cap and the warning level. Billed and estimated spend are shown apart.",
      },
    ],
  },
  connections: {
    icon: Cable,
    title: "Connections",
    lead: "Mail, storage and chat accounts. Each shows plainly what was granted and what the app actually reads.",
    items: [
      {
        icon: Mail,
        title: "Mailbox",
        body: "Gmail or any IMAP and SMTP mailbox, for applying by email and spotting replies. A dedicated job-search mailbox is recommended.",
      },
      {
        icon: HardDrive,
        title: "Storage",
        body: "Google Drive for each application's final files and shareable links.",
      },
      {
        icon: MessageCircle,
        title: "Chat",
        body: "A Telegram bot for notifications with Approve and Open buttons.",
      },
    ],
  },
  notifications: {
    icon: Bell,
    title: "Notifications",
    lead: "What reaches you, where, and when. Nothing goes out until a channel is connected.",
    items: [
      {
        icon: Bell,
        title: "Digest",
        body: "A daily summary after the morning sweep.",
      },
      {
        icon: MessageCircle,
        title: "Channels",
        body: "Telegram, email or a webhook, per kind of event.",
      },
    ],
  },
  runners: {
    icon: Bot,
    title: "Runners and tokens",
    lead: "Browser agents that fill application forms: Claude Code with Chrome on your PC, or an optional server runner.",
    items: [
      {
        icon: Bot,
        title: "Runners",
        body: "Each runner's last-seen time and what it is allowed to do.",
      },
      {
        icon: KeyRound,
        title: "Tokens",
        body: "Scoped, revocable tokens, shown once when created.",
      },
    ],
  },
  data: {
    icon: Database,
    title: "Data",
    lead: "Export and import, backups and retention.",
    items: [
      {
        icon: Archive,
        title: "Share setup",
        body: "Rubrics, templates, themes and rule types, scanned for personal details before export.",
      },
      {
        icon: Database,
        title: "Personal backup",
        body: "Everything, as one file you keep.",
      },
      {
        icon: RotateCcw,
        title: "Backups",
        body: "Nightly, encrypted, kept 14 by default, with a tested restore.",
      },
      {
        icon: FileClock,
        title: "Retention",
        body: "How long below-threshold and expired roles keep their full text.",
      },
    ],
  },
  security: {
    icon: Lock,
    title: "Security",
    lead: "Your password, two-step sign-in and active sessions.",
    items: [
      {
        icon: KeyRound,
        title: "Password",
        body: "Change it any time; at least 12 characters.",
      },
      {
        icon: ShieldCheck,
        title: "Two-step sign-in",
        body: "An authenticator app code at sign-in.",
      },
    ],
  },
  activity: {
    icon: ScrollText,
    title: "Activity log",
    lead: "The append-only audit trail. Every outward action traces to the facts used, the approval or gates that allowed it, the runner and the evidence.",
    items: [
      {
        icon: ScrollText,
        title: "Events",
        body: "Filter by actor, kind and date.",
      },
    ],
  },
  history: {
    icon: History,
    title: "Configuration history",
    lead: "Rules, prompts, rubrics, model routing and automation policy are versioned. Each run records the versions it used.",
    items: [
      {
        icon: History,
        title: "Versions",
        body: "Who changed what and when, with a diff.",
      },
      {
        icon: Undo2,
        title: "Rollback",
        body: "Return to an earlier version. Affects future work only.",
      },
    ],
  },
}

export function SettingsSection({
  section,
}: {
  section: keyof typeof SETTINGS_EMPTY
}) {
  const s = SETTINGS_EMPTY[section]
  return (
    <ScreenEmpty
      icon={s.icon}
      title={s.title}
      lead={s.lead}
      items={s.items}
      status="Not set up yet"
    />
  )
}
