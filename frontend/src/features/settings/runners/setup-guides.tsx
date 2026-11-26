import type { ReactNode } from "react"
import { SectionHeader } from "@/components/page-header"
import { TOKEN_ENV } from "./token-dialog"

/**
 * Commands as documented for `runner/local` and the `runner` compose profile (DESIGN 8.3).
 * They are kept here as constants so they can be corrected in one place if the kits change.
 */
export const LOCAL_COMMANDS = {
  install: "cd runner/local\n./install.sh",
  installWindows: "cd runner\\local\n.\\install.ps1",
  start: "./start.sh",
  startWindows: ".\\start.ps1",
} as const
export const SERVER_COMMANDS = {
  start: "docker compose --profile runner up -d",
  stop: "docker compose --profile runner down",
} as const

const Code = ({ children }: { children: ReactNode }) => (
  <pre className="overflow-x-auto rounded-md border border-border bg-sunken p-2.5 text-sm">
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

/** Step-by-step guides for the two kinds of runner. */
export function SetupGuides() {
  const mcpUrl =
    typeof window === "undefined" ? "/mcp" : `${window.location.origin}/mcp`
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
        <div className="mt-3 grid gap-2 text-sm">
          <p className="text-muted-foreground">
            Uses your own Chrome, so portals you have signed into stay signed
            in. It runs in a visible window and stops at logins and CAPTCHAs for
            you.
          </p>
          <ol className="grid list-decimal gap-2 pl-5">
            <li>
              Create a token above with <b>Where it runs</b> set to Your PC.
              Copy it.
            </li>
            <li>
              Install Claude Code and the Claude in Chrome extension, and sign
              in to Claude with your subscription. An API key does not work for
              the Chrome connection.
            </li>
            <li>
              Set the token in your environment as <code>{TOKEN_ENV}</code>.
            </li>
            <li>
              Install the kit from the Nchito folder. It adds the skill "work
              the Nchito queue" and an <code>.mcp.json</code> pointing at{" "}
              <code>{mcpUrl}</code>.<Code>{LOCAL_COMMANDS.install}</Code>
              On Windows:
              <Code>{LOCAL_COMMANDS.installWindows}</Code>
            </li>
            <li>
              Start it. It works the queue until it is empty or blocked.
              <Code>{LOCAL_COMMANDS.start}</Code>
              On Windows:
              <Code>{LOCAL_COMMANDS.startWindows}</Code>
            </li>
            <li>
              Come back to this page. The runner should show as Online within a
              minute.
            </li>
          </ol>
          <p className="text-muted-foreground">
            It works while that window is open. Close it and the runner shows as
            not responding here.
          </p>
        </div>
      </details>
      <details className="panel p-4">
        <summary className="cursor-pointer text-md">Server runner</summary>
        <div className="mt-3 grid gap-2 text-sm">
          <p className="rounded-md bg-warn-soft p-2.5 text-warn">
            This costs money. A server runner uses an Anthropic API key, so
            every task spends paid tokens. It has its own budget line and is{" "}
            <b>off by default</b>.
          </p>
          <ol className="grid list-decimal gap-2 pl-5">
            <li>
              Create a token above with <b>Where it runs</b> set to Server. Copy
              it.
            </li>
            <li>
              Add the token as <code>{TOKEN_ENV}</code> in the server's
              environment, together with your API key.
            </li>
            <li>
              Start it with the compose profile.
              <Code>{SERVER_COMMANDS.start}</Code>
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
