/**
 * Route tree (code-based TanStack Router).
 *
 *   /setup, /sign-in                      public
 *   (authed)                              guard: owner exists and signed in
 *     /onboarding?step=                   full-screen set-up guide
 *     (shell)                             AppShell: sidebar, top bar, palette
 *       /today /matches /applications /jobs/$id?tab= /studio /autopilot
 *       /kit/{library,tracks,guardrails,answers,documents,templates}
 *       /campaigns /sources /insights
 *       /settings/{appearance,ai,connections,notifications,runners,data,security,activity,history}
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
import { TodayPage } from "@/features/today/today-page"
import { MatchesPage } from "@/features/matches/matches-page"
import { ApplicationsPage } from "@/features/applications/applications-page"
import { JOB_TABS, JobPage } from "@/features/jobs/job-page"
import { StudioPage } from "@/features/studio/studio-page"
import { AutopilotPage } from "@/features/autopilot/autopilot-page"
import { KitLayout, KitSection } from "@/features/kit/kit-pages"
import { CampaignsPage } from "@/features/campaigns/campaigns-page"
import { SourcesPage } from "@/features/sources/sources-page"
import { RunsPage } from "@/features/sources/runs/runs-page"
import { RunDetailPage } from "@/features/sources/runs/run-detail-page"
import { InsightsPage } from "@/features/insights/insights-page"
import {
  SettingsLayout,
  SettingsSection,
} from "@/features/settings/settings-pages"
import { AppearancePage } from "@/features/settings/appearance-page"
import { OnboardingPage } from "@/features/onboarding/onboarding-page"

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
  step: z.coerce.number().int().min(1).max(6).catch(2).default(2),
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
  component: () => React.ReactNode
) =>
  createRoute({
    getParentRoute: () => shellRoute,
    path,
    staticData: { title },
    component,
  })

const todayRoute = page("/today", "Today", TodayPage)
const matchesRoute = page("/matches", "Matches", MatchesPage)
const applicationsRoute = page(
  "/applications",
  "Applications",
  ApplicationsPage
)
const studioRoute = page("/studio", "Studio", StudioPage)
const autopilotRoute = page("/autopilot", "Autopilot", AutopilotPage)
const runsRoute = page("/autopilot/runs", "Run history", RunsPage)
const runDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/autopilot/runs/$runId",
  staticData: { title: "Run" },
  component: function RunDetailRoute() {
    return <RunDetailPage runId={runDetailRoute.useParams().runId} />
  },
})
const campaignsRoute = page("/campaigns", "Campaigns", CampaignsPage)
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
type SettingsKey =
  | "ai"
  | "connections"
  | "notifications"
  | "runners"
  | "data"
  | "security"
  | "activity"
  | "history"
const settingsChild = (path: SettingsKey) =>
  createRoute({
    getParentRoute: () => settingsRoute,
    path,
    component: () => <SettingsSection section={path} />,
  })
const settingsChildren = [
  settingsChild("ai"),
  settingsChild("connections"),
  settingsChild("notifications"),
  settingsChild("runners"),
  settingsChild("data"),
  settingsChild("security"),
  settingsChild("activity"),
  settingsChild("history"),
] as const

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
      studioRoute,
      autopilotRoute,
      runsRoute,
      runDetailRoute,
      kitRoute.addChildren([kitIndex, ...kitChildren]),
      campaignsRoute,
      sourcesRoute,
      insightsRoute,
      settingsRoute.addChildren([
        settingsIndex,
        appearanceRoute,
        ...settingsChildren,
      ]),
      devComponentsRoute,
    ]),
  ]),
])
