import { Link } from "@tanstack/react-router"
import { PageHeader } from "@/components/page-header"
import { RunnersSection } from "./runners-section"
import { RunnerSettings } from "./runner-settings"
import { RunnerRules, SetupGuides } from "./setup-guides"
import { TokensSection } from "./tokens-section"

/** Settings > Runners: tokens, runners, their settings, what they may do, and how to set one up. */
export function RunnersPage() {
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Runners and tokens"
        description="Browser agents that fill in application forms: Claude Code with Chrome on your PC, or an optional server runner."
        actions={
          <Link
            to="/accounts"
            className="text-primary underline underline-offset-2"
          >
            Portal accounts
          </Link>
        }
      />
      <RunnerRules />
      <RunnersSection />
      <TokensSection />
      <RunnerSettings />
      <SetupGuides />
    </div>
  )
}
