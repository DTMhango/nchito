/**
 * Every command and environment variable name the runner setup guides show, in one place so
 * they can follow the runner kits if those change. Sources:
 *
 * - `runner/local/install.ps1`, `install.sh`, `start.ps1`, `start.sh`, `check.ps1`, `check.sh`,
 *   `mcp.template.json`, `scheduled/register-task.ps1` and `UNATTENDED.md`
 * - `runner/server/nchito_runner/config.py` and `runner/server/Dockerfile`
 * - `docker-compose.yml` (service `runner`, profile `runner`) and `docs/RUNBOOK.md`
 *
 * The token itself never appears here: the guides show TOKEN_PLACEHOLDER and the owner pastes
 * the one shown once when the token is created.
 */

/** Stands in for the runner token wherever a command needs it. */
export const TOKEN_PLACEHOLDER = "<your token>"
/** Stands in for this instance's address when the page cannot know it. */
export const INSTANCE_PLACEHOLDER = "https://<your instance>"
/** Stands in for the server runner's own Anthropic API key. */
export const API_KEY_PLACEHOLDER = "<your Anthropic API key>"

/** Environment variable names, with the kit file that reads each. */
export const RUNNER_ENV = {
  /** The instance address (install.ps1 -Url, start.*, check.*, mcp.template.json). */
  url: "NCHITO_URL",
  /** The bearer token (install.ps1 -SetToken, start.*, mcp.template.json, server config.py). */
  token: "NCHITO_RUNNER_TOKEN",
  /** install.sh: where the kit is installed (default ~/.nchito-runner). */
  home: "NCHITO_RUNNER_HOME",
  /** start.sh: keep a /loop session open at this interval (start.ps1 -Loop). */
  loop: "NCHITO_LOOP",
  /** start.sh: no permission prompts, self-check first (start.ps1 -Unattended). */
  unattended: "NCHITO_UNATTENDED",
  /** Server runner (config.py): the gateway endpoint. */
  serverMcpUrl: "NCHITO_MCP_URL",
  /** Server runner: its own key, separate spend (set from RUNNER_ANTHROPIC_API_KEY). */
  serverApiKey: "ANTHROPIC_API_KEY",
} as const

/** Compose variables for the `runner` service (docker-compose.yml). */
export const COMPOSE_ENV = {
  /** Becomes NCHITO_RUNNER_TOKEN inside the container. */
  token: "RUNNER_TOKEN",
  /** Becomes ANTHROPIC_API_KEY inside the container (its own spend line). */
  apiKey: "RUNNER_ANTHROPIC_API_KEY",
  /** Becomes NCHITO_MCP_URL (defaults to the web service's /mcp). */
  mcpUrl: "RUNNER_MCP_URL",
} as const

/** The compose profile that alone starts the server runner. */
export const COMPOSE_PROFILE = "runner"
/** The compose service name. */
export const COMPOSE_SERVICE = "runner"
/** The setting that lets the server runner take tasks (RUNBOOK, server runner step 1). */
export const SERVER_RUNNER_SETTING = "runners.server_runner_enabled"

const PS = "powershell -NoProfile -ExecutionPolicy Bypass -File"
const WIN_HOME = "$env:USERPROFILE\\.nchito-runner"
const NIX_HOME = "~/.nchito-runner"

/** Local runner (Your PC). `url` is this instance's address, e.g. window.location.origin. */
export const LOCAL_COMMANDS = {
  /** install.ps1: saves NCHITO_URL, prompts (hidden) for the token and saves NCHITO_RUNNER_TOKEN. */
  installWindows: (url: string) =>
    `${PS} runner\\local\\install.ps1 -Url ${url} -SetToken`,
  /** install.sh: the two variables must already be exported; it never stores the token. */
  installBash: (url: string) =>
    [
      `export ${RUNNER_ENV.url}=${url}`,
      `export ${RUNNER_ENV.token}=${TOKEN_PLACEHOLDER}`,
      "bash runner/local/install.sh",
    ].join("\n"),
  checkWindows: `powershell -File "${WIN_HOME}\\check.ps1"`,
  checkBash: `${NIX_HOME}/check.sh`,
  dryRunWindows: `${PS} "${WIN_HOME}\\start.ps1" -Arguments dry-run`,
  dryRunBash: `${NIX_HOME}/start.sh dry-run`,
  startWindows: `${PS} "${WIN_HOME}\\start.ps1"`,
  startBash: `${NIX_HOME}/start.sh`,
  /** Unattended (UNATTENDED.md, option C): a sign-in task that keeps a /loop session open. */
  registerTaskWindows: `${PS} "${WIN_HOME}\\scheduled\\register-task.ps1" -Interval 30m`,
} as const

/** Server runner (docker-compose.yml service `runner`, profile `runner`). */
export const SERVER_COMMANDS = {
  /** Lines for the server's environment (Dokploy, or `.env` locally). */
  env: [
    `${COMPOSE_ENV.token}=${TOKEN_PLACEHOLDER}`,
    `${COMPOSE_ENV.apiKey}=${API_KEY_PLACEHOLDER}`,
  ].join("\n"),
  start: `docker compose --profile ${COMPOSE_PROFILE} up -d --build ${COMPOSE_SERVICE}`,
  logs: `docker compose logs -f ${COMPOSE_SERVICE}`,
  stop: `docker compose stop ${COMPOSE_SERVICE}`,
} as const

/** Every command string, for tests that check no token-like literal slipped in. */
export const ALL_COMMANDS = (url: string): string[] => [
  LOCAL_COMMANDS.installWindows(url),
  LOCAL_COMMANDS.installBash(url),
  LOCAL_COMMANDS.checkWindows,
  LOCAL_COMMANDS.checkBash,
  LOCAL_COMMANDS.dryRunWindows,
  LOCAL_COMMANDS.dryRunBash,
  LOCAL_COMMANDS.startWindows,
  LOCAL_COMMANDS.startBash,
  LOCAL_COMMANDS.registerTaskWindows,
  SERVER_COMMANDS.env,
  SERVER_COMMANDS.start,
  SERVER_COMMANDS.logs,
  SERVER_COMMANDS.stop,
]
