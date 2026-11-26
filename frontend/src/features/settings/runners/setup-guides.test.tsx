import { describe, expect, it } from "vitest"
import { screen } from "@testing-library/react"
import { renderWithTheme } from "@/test/render"
import { SetupGuides } from "./setup-guides"
import {
  ALL_COMMANDS,
  COMPOSE_ENV,
  COMPOSE_PROFILE,
  LOCAL_COMMANDS,
  RUNNER_ENV,
  SERVER_COMMANDS,
  TOKEN_PLACEHOLDER,
} from "./setup-constants"

const URL = "https://nchito.example.com"

describe("runner setup constants", () => {
  it("use the names the runner kits read", () => {
    expect(RUNNER_ENV.url).toBe("NCHITO_URL")
    expect(RUNNER_ENV.token).toBe("NCHITO_RUNNER_TOKEN")
    expect(COMPOSE_ENV.token).toBe("RUNNER_TOKEN")
    expect(COMPOSE_ENV.apiKey).toBe("RUNNER_ANTHROPIC_API_KEY")
    expect(COMPOSE_PROFILE).toBe("runner")
  })

  it("build the install and start commands of runner/local", () => {
    expect(LOCAL_COMMANDS.installWindows(URL)).toBe(
      `powershell -NoProfile -ExecutionPolicy Bypass -File runner\\local\\install.ps1 -Url ${URL} -SetToken`
    )
    expect(LOCAL_COMMANDS.installBash(URL)).toContain(
      `export NCHITO_URL=${URL}`
    )
    expect(LOCAL_COMMANDS.installBash(URL)).toContain(
      "bash runner/local/install.sh"
    )
    expect(LOCAL_COMMANDS.startWindows).toContain(".nchito-runner\\start.ps1")
    expect(LOCAL_COMMANDS.dryRunBash).toBe("~/.nchito-runner/start.sh dry-run")
    expect(SERVER_COMMANDS.start).toBe(
      "docker compose --profile runner up -d --build runner"
    )
  })

  it("never carry a token, only the placeholder", () => {
    const all = ALL_COMMANDS(URL).join("\n")
    expect(all).not.toMatch(/nch_\w/)
    expect(LOCAL_COMMANDS.installBash(URL)).toContain(
      `NCHITO_RUNNER_TOKEN=${TOKEN_PLACEHOLDER}`
    )
    expect(SERVER_COMMANDS.env).toContain(`RUNNER_TOKEN=${TOKEN_PLACEHOLDER}`)
  })
})

describe("SetupGuides", () => {
  it("shows the commands from the constants file", () => {
    renderWithTheme(<SetupGuides />)
    const origin = window.location.origin
    expect(
      screen.getByText(LOCAL_COMMANDS.installWindows(origin))
    ).toBeInTheDocument()
    expect(screen.getByText(SERVER_COMMANDS.start)).toBeInTheDocument()
    expect(screen.getAllByText("RUNNER_TOKEN").length).toBeGreaterThan(0)
    expect(screen.getAllByText("NCHITO_RUNNER_TOKEN").length).toBeGreaterThan(0)
  })
})
