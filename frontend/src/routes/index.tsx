/**
 * Route tree (code-based TanStack Router).
 *
 *   /setup, /sign-in                      public
 *   (authed)                              guard: owner exists and signed in
 *     /onboarding?step=                   full-screen set-up guide
 *     (shell)                             AppShell: sidebar, top bar, palette
 *       /today?action= /matches /applications /jobs/$id?tab= /compare?ids= /studio?application=&run= /autopilot
 *       /kit/{library,tracks,guardrails,answers,documents,templates}
 *       /campaigns /sources /insights
 *       /settings/{appearance,ai,connections,notifications,runners,tracking,interview,accounts,sources,data,health,security,activity,history}
 *       /dev/components                   dev builds only
 *
 * To add a screen: write the page in src/features/<area>/, add a createRoute below under
 * shellRoute with staticData.title, add it to the tree, and (if it belongs in navigation)
 * add it to src/app/shell/nav.ts.
 */
import {
  createRootRouteWithContext,
  createRoute,
  lazyRouteComponent,
  Outlet,
  redirect,
} from "@tanstack/react-router"
import { lazy, type ComponentType } from "react"
import { z } from "zod"
import {
  requireNoOwner,
  requireSession,
  requireSignedOut,
  type RouterContext,
} from "@/app/guard"
import { AppShell } from "@/app/shell/app-shell"
import { SetupPage } from "@/features/auth/setup-page"
import { SignInPage } from "@/features/auth/sign-in-page"
import { matchesSearchSchema } from "@/features/matches/filters"
import { JOB_TABS } from "@/features/jobs/job-tabs"
import { compareSearchSchema } from "@/features/jobs/compare/api"
import { studioSearchSchema } from "@/features/studio/search"
import type { SettingsPageKey } from "@/features/settings/settings-group-page"
import { OnboardingPage } from "@/features/onboarding/onboarding-page"

/**
 * Screens load on demand, one chunk per area (the shell, sign-in and set-up stay in the main
 * bundle). The router shows RoutePending (app/router.tsx) while a chunk loads.
 */
function lazyPage<
  K extends string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  M extends Record<K, ComponentType<any>>,
>(load: () => Promise<M>, name: K) {
  return lazy(async () => ({ default: (await load())[name] }))
}
const TodayPage = lazyPage(
  () => import("@/features/today/today-page"),
  "TodayPage"
)
const MatchesPage = lazyPage(
  () => import("@/features/matches/matches-page"),
  "MatchesPage"
)
const ApplicationsPage = lazyPage(
  () => import("@/features/applications/applications-page"),
  "ApplicationsPage"
)
const JobPage = lazyPage(() => import("@/features/jobs/job-page"), "JobPage")
const ComparePage = lazyPage(
  () => import("@/features/jobs/compare/compare-page"),
  "ComparePage"
)
const StudioPage = lazyPage(
  () => import("@/features/studio/studio-page"),
  "StudioPage"
)
const AutopilotPage = lazyPage(
  () => import("@/features/autopilot/autopilot-page"),
  "AutopilotPage"
)
const ApprovalsPage = lazyPage(
  () => import("@/features/approvals/approvals-page"),
  "ApprovalsPage"
)
const ApprovalReviewPage = lazyPage(
  () => import("@/features/approvals/review-page"),
  "ReviewPage"
)
const KitLayout = lazyPage(
  () => import("@/features/kit/kit-pages"),
  "KitLayout"
)
const KitSection = lazyPage(
  () => import("@/features/kit/kit-pages"),
  "KitSection"
)
const CampaignsPage = lazyPage(
  () => import("@/features/campaigns/campaigns-page"),
  "CampaignsPage"
)
const CampaignEditorPage = lazyPage(
  () => import("@/features/campaigns/campaign-editor-page"),
  "CampaignEditorPage"
)
const SourcesPage = lazyPage(
  () => import("@/features/sources/sources-page"),
  "SourcesPage"
)
const RunsPage = lazyPage(
  () => import("@/features/sources/runs/runs-page"),
  "RunsPage"
)
const RunDetailPage = lazyPage(
  () => import("@/features/sources/runs/run-detail-page"),
  "RunDetailPage"
)
const InsightsPage = lazyPage(
  () => import("@/features/insights/insights-page"),
  "InsightsPage"
)
const SettingsLayout = lazyPage(
  () => import("@/features/settings/settings-pages"),
  "SettingsLayout"
)
const AppearancePage = lazyPage(
  () => import("@/features/settings/appearance-page"),
  "AppearancePage"
)
const ThemeStudioPage = lazyPage(
  () => import("@/features/theme-studio/theme-studio-page"),
  "ThemeStudioPage"
)
const AiSettingsPage = lazyPage(
  () => import("@/features/settings/ai/ai-page"),
  "AiSettingsPage"
)
const SettingsGroupPage = lazyPage(
  () => import("@/features/settings/settings-group-page"),
  "SettingsGroupPage"
)
const ActivityPage = lazyPage(
  () => import("@/features/settings/activity-page"),
  "ActivityPage"
)
const HistoryPage = lazyPage(
  () => import("@/features/settings/history-page"),
  "HistoryPage"
)
const ConnectionsPage = lazyPage(
  () => import("@/features/settings/connections/connections-page"),
  "ConnectionsPage"
)
const RunnersPage = lazyPage(
  () => import("@/features/settings/runners/runners-page"),
  "RunnersPage"
)
const AccountsPage = lazyPage(
  () => import("@/features/accounts/accounts-page"),
  "AccountsPage"
)
const HandoffPage = lazyPage(
  () => import("@/features/accounts/handoff-page"),
  "HandoffPage"
)
const DataPage = lazyPage(
  () => import("@/features/settings/data/data-page"),
  "DataPage"
)
const NotificationsPage = lazyPage(
  () => import("@/features/settings/notifications/notifications-page"),
  "NotificationsPage"
)
const HealthPanel = lazyPage(
  () => import("@/features/settings/health/health-panel"),
  "HealthPanel"
)
const SecurityPage = lazyPage(
  () => import("@/features/settings/security-page"),
  "SecurityPage"
)

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** Shown in the top bar and the document title. */
    title?: string
  }
}

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
})

// ---- public ----
const setupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/setup",
  staticData: { title: "Set up" },
  beforeLoad: ({ context }) => requireNoOwner({ context }),
  component: SetupPage,
})

const signInSearch = z.object({ redirect: z.string().optional() })
const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sign-in",
  staticData: { title: "Sign in" },
  validateSearch: signInSearch,
  beforeLoad: ({ context, search }) => requireSignedOut({ context, search }),
  component: function SignInRoute() {
    const { redirect: to } = signInRoute.useSearch()
    return <SignInPage redirectTo={to} />
  },
})

// ---- authed ----
const authedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "authed",
  beforeLoad: ({ context, location }) => requireSession({ context, location }),
  component: Outlet,
})

const onboardingSearch = z.object({
  step: z.coerce.number().int().min(1).max(8).catch(1).default(1),
})
const onboardingRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/onboarding",
  staticData: { title: "Set-up guide" },
  validateSearch: onboardingSearch,
  component: function OnboardingRoute() {
    const { step } = onboardingRoute.useSearch()
    return <OnboardingPage step={step} />
  },
})

const shellRoute = createRoute({
  getParentRoute: () => authedRoute,
  id: "shell",
  component: AppShell,
})

const indexRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/today" })
  },
})

const page = <P extends string>(
  path: P,
  title: string,
  Component: ComponentType
) =>
  createRoute({
    getParentRoute: () => shellRoute,
    path,
    staticData: { title },
    component: () => <Component />,
  })

/** `?action=<pending action id>`: Today opens that decision (the Studio's question links). */
const todaySearch = z.object({ action: z.string().optional().catch(undefined) })
const todayRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/today",
  staticData: { title: "Today" },
  validateSearch: todaySearch,
  component: function TodayRoute() {
    const { action } = todayRoute.useSearch()
    return <TodayPage focusAction={action} />
  },
})
const matchesRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/matches",
  staticData: { title: "Matches" },
  validateSearch: matchesSearchSchema,
  component: function MatchesRoute() {
    const search = matchesRoute.useSearch()
    const navigate = matchesRoute.useNavigate()
    return (
      <MatchesPage
        search={search}
        onSearch={(next, opts) =>
          void navigate({ search: next, replace: opts?.replace })
        }
      />
    )
  },
})
const applicationsRoute = page(
  "/applications",
  "Applications",
  ApplicationsPage
)
const studioRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/studio",
  staticData: { title: "Studio" },
  validateSearch: studioSearchSchema,
  component: function StudioRoute() {
    const search = studioRoute.useSearch()
    const navigate = studioRoute.useNavigate()
    return (
      <StudioPage
        search={search}
        onSearch={(next) => void navigate({ search: next, replace: true })}
      />
    )
  },
})
const autopilotRoute = page("/autopilot", "Autopilot", AutopilotPage)
const approvalsRoute = page("/approvals", "Approvals", ApprovalsPage)
const approvalReviewRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/approvals/$applicationId",
  staticData: { title: "Review" },
  component: function ApprovalReviewRoute() {
    return (
      <ApprovalReviewPage
        applicationId={approvalReviewRoute.useParams().applicationId}
      />
    )
  },
})
const runsRoute = page("/autopilot/runs", "Run history", RunsPage)
const runDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/autopilot/runs/$runId",
  staticData: { title: "Run" },
  component: function RunDetailRoute() {
    return <RunDetailPage runId={runDetailRoute.useParams().runId} />
  },
})
const accountsRoute = page("/accounts", "Portal accounts", AccountsPage)
const handoffRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/accounts/handoff/$actionId",
  staticData: { title: "Sign-in handoff" },
  component: function HandoffRoute() {
    return <HandoffPage actionId={handoffRoute.useParams().actionId} />
  },
})
const campaignsRoute = page("/campaigns", "Campaigns", CampaignsPage)
const campaignEditorRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/campaigns/$id",
  staticData: { title: "Campaign" },
  component: function CampaignEditorRoute() {
    return <CampaignEditorPage id={campaignEditorRoute.useParams().id} />
  },
})
const themeStudioRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/theme-studio/$themeId",
  staticData: { title: "Theme studio" },
  component: function ThemeStudioRoute() {
    return <ThemeStudioPage themeId={themeStudioRoute.useParams().themeId} />
  },
})
const sourcesRoute = page("/sources", "Sources", SourcesPage)
const insightsRoute = page("/insights", "Insights", InsightsPage)

const jobSearch = z.object({
  tab: z.enum(JOB_TABS).catch("overview").default("overview"),
})
const jobRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/jobs/$id",
  staticData: { title: "Role" },
  validateSearch: jobSearch,
  component: function JobRoute() {
    const { id } = jobRoute.useParams()
    const { tab } = jobRoute.useSearch()
    return <JobPage id={id} tab={tab} />
  },
})

const compareRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/compare",
  staticData: { title: "Compare roles" },
  validateSearch: compareSearchSchema,
  component: function CompareRoute() {
    const { ids } = compareRoute.useSearch()
    const navigate = compareRoute.useNavigate()
    return (
      <ComparePage
        ids={ids}
        onIds={(next) =>
          void navigate({ search: { ids: next }, replace: true })
        }
      />
    )
  },
})

// ---- Kit ----
const kitRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/kit",
  staticData: { title: "Kit" },
  component: KitLayout,
})
const kitIndex = createRoute({
  getParentRoute: () => kitRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/kit/library" })
  },
})
const kitChild = (
  path:
    "library" | "tracks" | "guardrails" | "answers" | "documents" | "templates"
) =>
  createRoute({
    getParentRoute: () => kitRoute,
    path,
    component: () => <KitSection section={path} />,
  })
const kitChildren = [
  kitChild("library"),
  kitChild("tracks"),
  kitChild("guardrails"),
  kitChild("answers"),
  kitChild("documents"),
  kitChild("templates"),
] as const

// ---- Settings ----
const settingsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/settings",
  staticData: { title: "Settings" },
  component: SettingsLayout,
})
const settingsIndex = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/settings/appearance" })
  },
})
const appearanceRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "appearance",
  staticData: { title: "Appearance" },
  component: AppearancePage,
})
const groupRoute = (path: SettingsPageKey) =>
  createRoute({
    getParentRoute: () => settingsRoute,
    path,
    component: () => <SettingsGroupPage page={path} />,
  })
const groupRoutes = [
  groupRoute("general"),
  groupRoute("schedule"),
  groupRoute("scoring"),
  groupRoute("automation"),
  groupRoute("documents"),
  groupRoute("retention"),
  groupRoute("reconcile"),
  groupRoute("tracking"),
  groupRoute("interview"),
  groupRoute("accounts"),
  groupRoute("sources"),
] as const
const ownRoute = (
  path:
    | "security"
    | "activity"
    | "history"
    | "connections"
    | "data"
    | "notifications"
    | "runners"
    | "health",
  C: ComponentType
) =>
  createRoute({
    getParentRoute: () => settingsRoute,
    path,
    component: () => <C />,
  })
const ownRoutes = [
  ownRoute("security", SecurityPage),
  ownRoute("activity", ActivityPage),
  ownRoute("history", HistoryPage),
  ownRoute("connections", ConnectionsPage),
  ownRoute("data", DataPage),
  ownRoute("notifications", NotificationsPage),
  ownRoute("runners", RunnersPage),
  ownRoute("health", HealthPanel),
] as const
const aiRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "ai",
  staticData: { title: "AI" },
  component: AiSettingsPage,
})
const settingsChildren = [aiRoute] as const

// ---- dev ----
const devComponentsRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/dev/components",
  staticData: { title: "Components" },
  beforeLoad: () => {
    if (!import.meta.env.DEV) throw redirect({ to: "/today" })
  },
  component: lazyRouteComponent(
    () => import("@/features/dev/components-page"),
    "ComponentsPage"
  ),
})

export const routeTree = rootRoute.addChildren([
  setupRoute,
  signInRoute,
  authedRoute.addChildren([
    onboardingRoute,
    shellRoute.addChildren([
      indexRoute,
      todayRoute,
      matchesRoute,
      applicationsRoute,
      jobRoute,
      compareRoute,
      studioRoute,
      autopilotRoute,
      approvalsRoute,
      approvalReviewRoute,
      runsRoute,
      runDetailRoute,
      accountsRoute,
      handoffRoute,
      kitRoute.addChildren([kitIndex, ...kitChildren]),
      campaignsRoute,
      campaignEditorRoute,
      themeStudioRoute,
      sourcesRoute,
      insightsRoute,
      settingsRoute.addChildren([
        settingsIndex,
        appearanceRoute,
        ...groupRoutes,
        ...ownRoutes,
        ...settingsChildren,
      ]),
      devComponentsRoute,
    ]),
  ]),
])
