import {
  BarChart3,
  Bot,
  Briefcase,
  Columns3,
  FileCheck2,
  FileText,
  Gauge,
  Inbox,
  Radio,
  UserRoundCheck,
  Settings,
  Sun,
  Target,
  type LucideIcon,
} from "lucide-react"
import type { LinkProps } from "@tanstack/react-router"

/** Any path the router knows. Checked at compile time. */
export type AppPath = NonNullable<LinkProps["to"]>

export type NavItem = {
  to: AppPath
  label: string
  icon: LucideIcon
  /** Shown in the phone tab bar (others go under More). */
  phone?: boolean
  /** Words the command palette also matches. */
  keywords?: string[]
}

/** Daily work, top of the sidebar. */
export const NAV_MAIN: NavItem[] = [
  {
    to: "/today",
    label: "Today",
    icon: Sun,
    phone: true,
    keywords: ["home", "needs you", "dashboard"],
  },
  {
    to: "/matches",
    label: "Matches",
    icon: Inbox,
    phone: true,
    keywords: ["jobs", "roles", "triage"],
  },
  {
    to: "/applications",
    label: "Applications",
    icon: Columns3,
    phone: true,
    keywords: ["pipeline", "board", "stages"],
  },
  {
    to: "/studio",
    label: "Studio",
    icon: FileText,
    keywords: ["cv", "letter", "tailor", "documents"],
  },
  {
    to: "/approvals",
    label: "Approvals",
    icon: FileCheck2,
    keywords: ["approve", "packet", "review", "send", "needs you"],
  },
  {
    to: "/autopilot",
    label: "Autopilot",
    icon: Gauge,
    phone: true,
    keywords: ["automation", "thresholds", "caps", "runs"],
  },
]

/** Setup and review, below the divider. */
export const NAV_SETUP: NavItem[] = [
  {
    to: "/kit",
    label: "Kit",
    icon: Briefcase,
    keywords: ["library", "facts", "guardrails", "answers", "profile"],
  },
  {
    to: "/campaigns",
    label: "Campaigns",
    icon: Target,
    keywords: ["search", "criteria", "rubric", "schedule"],
  },
  {
    to: "/sources",
    label: "Sources",
    icon: Radio,
    keywords: ["boards", "feeds", "employers", "health"],
  },
  {
    to: "/accounts",
    label: "Portal accounts",
    icon: UserRoundCheck,
    keywords: ["sign in", "login", "account", "portal", "workday", "handoff"],
  },
  {
    to: "/settings/runners",
    label: "Runners",
    icon: Bot,
    keywords: ["runner", "agent", "token", "browser", "pc", "server", "mcp"],
  },
  {
    to: "/insights",
    label: "Insights",
    icon: BarChart3,
    keywords: ["funnel", "response rate", "spend", "analytics"],
  },
]

export const NAV_FOOT: NavItem[] = [
  {
    to: "/settings",
    label: "Settings",
    icon: Settings,
    keywords: ["preferences", "appearance", "account"],
  },
]

export const KIT_SECTIONS = [
  { to: "/kit/library", label: "Library" },
  { to: "/kit/tracks", label: "Tracks" },
  { to: "/kit/guardrails", label: "Guardrails" },
  { to: "/kit/answers", label: "Answer bank" },
  { to: "/kit/documents", label: "Documents" },
  { to: "/kit/templates", label: "Templates" },
] as const satisfies readonly { to: AppPath; label: string }[]

export const SETTINGS_SECTIONS = [
  { to: "/settings/appearance", label: "Appearance" },
  { to: "/settings/general", label: "General" },
  { to: "/settings/schedule", label: "Schedule" },
  { to: "/settings/scoring", label: "Scoring" },
  { to: "/settings/automation", label: "Automation" },
  { to: "/settings/documents", label: "Documents" },
  { to: "/settings/retention", label: "Retention" },
  { to: "/settings/reconcile", label: "Reconcile" },
  { to: "/settings/tracking", label: "Tracking" },
  { to: "/settings/interview", label: "Interview" },
  { to: "/settings/sources", label: "Discovery" },
  { to: "/settings/accounts", label: "Portal accounts" },
  { to: "/settings/ai", label: "AI" },
  { to: "/settings/connections", label: "Connections" },
  { to: "/settings/notifications", label: "Notifications" },
  { to: "/settings/runners", label: "Runners" },
  { to: "/settings/data", label: "Data" },
  { to: "/settings/health", label: "System health" },
  { to: "/settings/security", label: "Security" },
  { to: "/settings/activity", label: "Activity log" },
  { to: "/settings/history", label: "Configuration history" },
] as const satisfies readonly { to: AppPath; label: string }[]
