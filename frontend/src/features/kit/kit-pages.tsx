import { Outlet } from "@tanstack/react-router"
import {
  Award,
  BookOpen,
  Briefcase,
  CircleSlash,
  FileBadge,
  FileText,
  Layers,
  LayoutTemplate,
  ListChecks,
  MessageSquareQuote,
  Repeat2,
  Shield,
  ShieldAlert,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react"
import { ScreenEmpty, type WhatAppears } from "@/components/empty-state"
import { SubNav, SubNavLink } from "@/components/sub-nav"
import { View } from "@/components/view"
import { KIT_SECTIONS } from "@/app/shell/nav"

/** Kit: everything the app may say about you (DESIGN 5). Sub-nav over six sections. */
export function KitLayout() {
  return (
    <View>
      <SubNav label="Kit sections" className="mb-5">
        {KIT_SECTIONS.map((s) => (
          <SubNavLink key={s.to} to={s.to}>
            {s.label}
          </SubNavLink>
        ))}
      </SubNav>
      <Outlet />
    </View>
  )
}

type Section = {
  icon: LucideIcon
  title: string
  lead: string
  items: WhatAppears[]
  first: string
}

const SECTIONS: Record<
  "library" | "tracks" | "guardrails" | "answers" | "documents" | "templates",
  Section
> = {
  library: {
    icon: BookOpen,
    title: "Library",
    lead: "Facts are the unit of truth. A CV is a selection of approved facts, so everything here is something you have confirmed is true.",
    first: "Import your CVs or old kit",
    items: [
      {
        icon: Briefcase,
        title: "Experience",
        body: "Organisations, titles with dates, allowed title variants per track, and titles never to use.",
      },
      {
        icon: ListChecks,
        title: "Facts",
        body: "Each with an ID like F-112, its kind, tags and tracks, and a status: draft, approved or retired.",
      },
      {
        icon: Sparkles,
        title: "Skills",
        body: "Each marked yes, no or never claim. Never-claim skills are fed to the checker.",
      },
      {
        icon: Award,
        title: "Education and certificates",
        body: "Degrees, exams and certificates with issuers and dates.",
      },
      {
        icon: Users,
        title: "References",
        body: "Who, their consent, and when they may be shared.",
      },
      {
        icon: CircleSlash,
        title: "Needs review",
        body: "Anything imported waits here until you confirm, edit or drop it.",
      },
    ],
  },
  tracks: {
    icon: Layers,
    title: "Tracks",
    lead: "A track is a positioning: which facts lead, which title variants are allowed, and which summary opens. Changing a track never edits a fact.",
    first: "Create your first track",
    items: [
      {
        icon: Layers,
        title: "Positioning",
        body: "Name, priority and example job titles for each track.",
      },
      {
        icon: ListChecks,
        title: "Lead facts",
        body: "The facts that open the CV for this track.",
      },
      {
        icon: MessageSquareQuote,
        title: "Summary and tone",
        body: "The opening summary and notes on tone.",
      },
    ],
  },
  guardrails: {
    icon: Shield,
    title: "Guardrails",
    lead: "Typed rules checked by code first and a model second, over every document and the whole outgoing packet.",
    first: "Add a guardrail",
    items: [
      {
        icon: ShieldAlert,
        title: "Never mention",
        body: "Terms or patterns that must never appear, like a confidential figure or a tool you never used.",
      },
      {
        icon: Repeat2,
        title: "Never together",
        body: "Two facts that reveal something when they appear in the same packet.",
      },
      {
        icon: FileText,
        title: "Required wording",
        body: "Use A, not B: an official title, a certificate's exact issuer.",
      },
      {
        icon: Shield,
        title: "Attach policy and limits",
        body: "Which documents go when, and page and paragraph limits.",
      },
    ],
  },
  answers: {
    icon: MessageSquareQuote,
    title: "Answer bank",
    lead: "Application questions answered once and reused: notice period, work rights, salary expectations. Material answers ask first.",
    first: "Add an answer",
    items: [
      {
        icon: Repeat2,
        title: "Reuse freely",
        body: "Routine answers used on every form that asks.",
      },
      {
        icon: ShieldAlert,
        title: "Ask me first",
        body: "Material answers confirmed per use until you mark them settled.",
      },
      {
        icon: CircleSlash,
        title: "Never answer",
        body: "Questions to decline, or that only you may answer, like declarations.",
      },
      {
        icon: ListChecks,
        title: "Conditions",
        body: "Different answers by country, employment type or employer.",
      },
    ],
  },
  documents: {
    icon: FileBadge,
    title: "Documents",
    lead: "Certificates, transcripts, ID and references, each with a sensitivity that decides when it may be attached.",
    first: "Upload a document",
    items: [
      {
        icon: FileBadge,
        title: "Vault",
        body: "Each file typed: CV, degree, transcript, ID, photo, certificate.",
      },
      {
        icon: Shield,
        title: "Sensitivity",
        body: "Normal, on request, or after an offer only.",
      },
    ],
  },
  templates: {
    icon: LayoutTemplate,
    title: "Templates",
    lead: "CV, letter and email layouts with their limits. Three CV templates ship: Classic, Compact and Modern, all single-column and text-extractable.",
    first: "Preview the CV templates",
    items: [
      {
        icon: LayoutTemplate,
        title: "Layouts",
        body: "Section order, accent and type, rendered to PDF and Word.",
      },
      {
        icon: ListChecks,
        title: "Limits",
        body: "Pages, paragraphs and bullets per document.",
      },
    ],
  },
}

export function KitSection({ section }: { section: keyof typeof SECTIONS }) {
  const s = SECTIONS[section]
  return (
    <ScreenEmpty
      icon={s.icon}
      title={s.title}
      lead={s.lead}
      items={s.items}
      firstStep={{
        label: s.first,
        to: "/onboarding",
        hint: "The set-up guide imports and reviews in one pass.",
      }}
    />
  )
}
