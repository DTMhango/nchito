import type { ReactNode } from "react"
import { SectionHeader } from "@/components/page-header"
import {
  COMPOSE_ENV,
  COMPOSE_PROFILE,
  INSTANCE_PLACEHOLDER,
  LOCAL_COMMANDS,
  RUNNER_ENV,
  SERVER_COMMANDS,
  SERVER_RUNNER_SETTING,
} from "./setup-constants"

const Code = ({ children }: { children: ReactNode }) => (
  <pre className="my-1.5 min-w-0 overflow-x-auto rounded-md border border-border bg-sunken p-2.5 text-sm">
    <code>{children}</code>
  </pre>
)

/** What a runner may and may not do, and how far the server can enforce it (DESIGN 18.1). */
export function RunnerRules() {
  return (
    <section aria-labelledby="rules-h" className="grid gap-2 panel p-4 text-sm">
      <h3 id="rules-h" className="text-md">
        What a runner can and cannot do
      </h3>
      <ul className="grid list-disc gap-1 pl-5">
        <li>
          It never types a password and never creates an account. You do both.
        </li>
        <li>
          It presses Submit only when the server has granted a permit. A permit
          is for one application, lasts 10 minutes and works once.
        </li>
        <li>It never answers questions you have marked never or owner-only.</li>
        <li>
          It treats what a web page says as data, not as orders. If a page asks
          for something odd, it stops and tells you.
        </li>
        <li>
          It stays on the employer's domain. A redirect elsewhere stops it.
        </li>
      </ul>
      <p className="text-muted-foreground">
        On a browser, these rules are <b>instructed and audited</b>: the agent
        is told to follow them and normally does, and everything it does is
        recorded, but the server cannot physically stop a click on someone
        else's website. If a submission is seen without a permit, that runner is
        paused and you are told. Email is different: the server itself sends it,
        so nothing leaves without the checks.
      </p>
    </section>
  )
}

/** This instance's address, as the runner kits want it (no trailing slash). */
const instanceUrl = () =>
  typeof window === "undefined" ? INSTANCE_PLACEHOLDER : window.location.origin

/** Step-by-step guides for the two kinds of runner. Commands live in setup-constants.ts. */
export function SetupGuides() {
  const url = instanceUrl()
  return (
    <section aria-labelledby="guides-h" className="grid gap-3">
      <SectionHeader
        as="h3"
        title={<span id="guides-h">Set up a runner</span>}
        aside="Create a token first, then follow one guide."
      />
      <details className="panel p-4" open>
        <summary className="cursor-pointer text-md">
          Use my PC (Claude Code + Chrome)
        </summary>
        <div className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-2 text-sm">
          <p className="text-muted-foreground">
            Uses your own Chrome, so portals you have signed into stay signed
            in. It runs in a visible window and stops at logins and CAPTCHAs for
            you.
          </p>
          <ol className="grid list-decimal grid-cols-[minmax(0,1fr)] gap-2 pl-5">
            <li>
              Create a token above with <b>Where it runs</b> set to Your PC.
              Copy it.
            </li>
            <li>
              Install Claude Code and the Claude in Chrome extension, sign in to
              both with your Claude subscription (not an API key: Chrome stays
              off with one), and run <code>/chrome</code> once in Claude Code.
            </li>
            <li>
              From the Nchito folder, install the kit. It copies the skill "work
              the Nchito queue" and an MCP config pointing at{" "}
              <code>{url}/mcp</code>, and saves <code>{RUNNER_ENV.url}</code>{" "}
              and <code>{RUNNER_ENV.token}</code> as your user environment
              variables (never in a file). It asks for the token without showing
              it.
              <Code>{LOCAL_COMMANDS.installWindows(url)}</Code>
              On macOS, Linux or Git Bash, export both variables first (paste
              your token in place of the placeholder):
              <Code>{LOCAL_COMMANDS.installBash(url)}</Code>
            </li>
            <li>
              Open a new terminal and run the self-check (settings, server and
              token).
              <Code>{LOCAL_COMMANDS.checkWindows}</Code>
              Or: <Code>{LOCAL_COMMANDS.checkBash}</Code>
            </li>
            <li>
              First time, a dry run: it reads one form and enters nothing.
              <Code>{LOCAL_COMMANDS.dryRunWindows}</Code>
              Or: <Code>{LOCAL_COMMANDS.dryRunBash}</Code>
            </li>
            <li>
              Start it. It works the queue until it is empty or blocked.
              <Code>{LOCAL_COMMANDS.startWindows}</Code>
              Or: <Code>{LOCAL_COMMANDS.startBash}</Code>
            </li>
            <li>
              Come back to this page. The runner should show as Online within a
              minute.
            </li>
          </ol>
          <p className="text-muted-foreground">
            It works while that window is open. Close it and the runner shows as
            not responding here. To keep it going when you sign in to Windows,
            register the scheduled task (the PC must stay awake):
          </p>
          <Code>{LOCAL_COMMANDS.registerTaskWindows}</Code>
        </div>
      </details>
      <details className="panel p-4">
        <summary className="cursor-pointer text-md">Server runner</summary>
        <div className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-2 text-sm">
          <p className="rounded-md bg-warn-soft p-2.5 text-warn">
            This costs money. A server runner uses an Anthropic API key, so
            every task spends paid tokens. It has its own budget line and is{" "}
            <b>off by default</b>.
          </p>
          <ol className="grid list-decimal grid-cols-[minmax(0,1fr)] gap-2 pl-5">
            <li>
              Create a token above with <b>Where it runs</b> set to Server. Copy
              it. Turn on the setting <code>{SERVER_RUNNER_SETTING}</code>.
            </li>
            <li>
              Add the token as <code>{COMPOSE_ENV.token}</code> and its own API
              key as <code>{COMPOSE_ENV.apiKey}</code> in the server's
              environment (paste your values in place of the placeholders). The
              container reads them as <code>{RUNNER_ENV.token}</code> and{" "}
              <code>{RUNNER_ENV.serverApiKey}</code>.
              <Code>{SERVER_COMMANDS.env}</Code>
            </li>
            <li>
              Start it with the <code>{COMPOSE_PROFILE}</code> compose profile.
              Plain <code>docker compose up</code> never starts it.
              <Code>{SERVER_COMMANDS.start}</Code>
              Follow its log:
              <Code>{SERVER_COMMANDS.logs}</Code>
              Stop it any time with:
              <Code>{SERVER_COMMANDS.stop}</Code>
            </li>
          </ol>
          <p className="text-muted-foreground">
            It suits forms that need no account (Greenhouse, Lever, Ashby,
            Teamtailor, BambooHR). Roles that need you to sign in go to your PC
            runner.
          </p>
        </div>
      </details>
    </section>
  )
}
