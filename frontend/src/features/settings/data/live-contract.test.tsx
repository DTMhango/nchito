import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderApp } from "@/test/render"
import { aiMockState } from "@/mocks/handlers/ai"
import { dataMock } from "@/mocks/handlers/data"

describe("Connections against the wave 2 contract", () => {
  it("says which server variables to set when Google is not configured (409)", async () => {
    dataMock.googleConfigured = false
    const user = userEvent.setup()
    renderApp("/settings/connections")
    await user.click(
      await screen.findByRole("button", { name: "Connect Gmail" })
    )
    expect(
      await screen.findByText(
        "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET on the server to connect Google."
      )
    ).toBeInTheDocument()
  })

  it("confirms the return from Google", async () => {
    renderApp("/settings/connections?connected=gdrive")
    expect(
      await screen.findByText(/Google Drive is connected/)
    ).toBeInTheDocument()
  })

  it("refuses a webhook signing secret under 16 characters", async () => {
    const user = userEvent.setup()
    renderApp("/settings/connections")
    const form = await screen.findByRole("form", { name: "Add Webhook" })
    await user.type(
      within(form).getByLabelText("Webhook address"),
      "https://example.com/hook"
    )
    await user.type(within(form).getByLabelText("Signing secret"), "short")
    expect(
      within(form).getByText(/at least 16 characters\./)
    ).toBeInTheDocument()
    expect(
      within(form).getByRole("button", { name: "Connect webhook" })
    ).toBeDisabled()
  })

  it("changes a Telegram chat and keeps the saved token when left empty", async () => {
    aiMockState().connections.push({
      id: "t2",
      created_at: "",
      updated_at: "",
      provider: "telegram",
      label: "Alerts bot",
      config: { chat_id: "123" },
      secrets_masked: { bot_token: "********WXYZ" },
      scopes_granted: [],
      reads_description: null,
      health: "ok",
      last_checked_at: null,
      enabled: true,
    })
    const user = userEvent.setup()
    renderApp("/settings/connections")
    const card = await screen.findByRole("listitem", { name: "Alerts bot" })
    await user.click(
      within(card).getByRole("button", { name: "Change Alerts bot" })
    )
    const form = within(card).getByRole("form", { name: "Change Alerts bot" })
    expect(
      within(form).getByLabelText("Bot token", { exact: false })
    ).toHaveValue("")
    const chat = within(form).getByLabelText("Chat ID")
    await user.clear(chat)
    await user.type(chat, "456")
    await user.click(within(form).getByRole("button", { name: "Save changes" }))
    await waitFor(() =>
      expect(
        aiMockState().connections.find((c) => c.id === "t2")?.config
      ).toEqual({ chat_id: "456" })
    )
    expect(
      aiMockState().connections.find((c) => c.id === "t2")?.secrets_masked
    ).toEqual({ bot_token: "********WXYZ" })
    expect(document.body.textContent).not.toMatch(/WXYZ/)
  })
})

describe("Data against the wave 2 contract", () => {
  it("refuses a share export with personal details until acknowledged, then downloads", async () => {
    const user = userEvent.setup()
    renderApp("/settings/data")
    const share = await screen.findByRole("article", {
      name: "Shareable template",
    })
    await user.click(
      within(share).getByRole("button", { name: "See what is inside" })
    )
    await within(share).findByText(/1 personal detail found/)
    await user.click(within(share).getByRole("button", { name: /Create file/ }))
    expect(
      await within(share).findByText(/Personal details were found/)
    ).toBeInTheDocument()
    expect(
      within(share).queryByRole("button", { name: /^Download/ })
    ).toBeNull()

    await user.click(
      within(share).getByRole("checkbox", {
        name: /I have read these and want to include them/,
      })
    )
    await user.click(within(share).getByRole("button", { name: /Create file/ }))
    const download = await within(share).findByRole("button", {
      name: "Download setup-template.kit.zip",
    })
    expect(within(share).queryByText(/Personal details were found/)).toBeNull()
    expect(download).toBeEnabled()
  })

  it("says the download expired when the link answers 404", async () => {
    const user = userEvent.setup()
    renderApp("/settings/data")
    const backup = await screen.findByRole("article", {
      name: "Personal backup",
    })
    await user.click(
      within(backup).getByRole("button", { name: "See what is inside" })
    )
    await within(backup).findByRole("list", {
      name: "What Personal backup contains",
    })
    await user.click(
      within(backup).getByRole("button", { name: /Create file/ })
    )
    const download = await within(backup).findByRole("button", {
      name: "Download personal.kit.zip",
    })
    // The link lifetime (data.export_link_minutes) has passed.
    dataMock.exportsExpired = true
    await user.click(download)
    expect(
      await within(backup).findByText("This file has expired. Create it again.")
    ).toBeInTheDocument()
  })

  it("explains a missing pg_dump in plain words (503)", async () => {
    dataMock.pgDump = false
    const user = userEvent.setup()
    renderApp("/settings/data")
    await screen.findByText(/Last backup:/)
    await user.click(screen.getByRole("button", { name: "Back up now" }))
    expect(
      await screen.findByText(/need the PostgreSQL tool pg_dump/)
    ).toBeInTheDocument()
  })
})

describe("Health, notifications and history against the wave 2 contract", () => {
  it("never shows an unknown component as OK", async () => {
    renderApp("/settings/health")
    const sweep = await screen.findByRole("listitem", { name: "Last sweep" })
    expect(within(sweep).getByText("Unknown")).toBeInTheDocument()
    expect(within(sweep).queryByText("OK")).toBeNull()
    const disk = screen.getByRole("listitem", { name: "Disk space" })
    expect(within(disk).getByText("Needs a look")).toBeInTheDocument()
  })

  it("uses the notifications settings and shows a validation error", async () => {
    const user = userEvent.setup()
    renderApp("/settings/notifications")
    const quiet = await screen.findByRole("list", { name: "Quiet hours" })
    expect(
      within(quiet).getByText("Notification quiet hours start")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("list", { name: "What notifies you" })
    ).toBeInTheDocument()
    const digest = screen.getByRole("list", { name: "Digest" })
    const length = within(digest).getByLabelText("Digest list length")
    await user.clear(length)
    await user.type(length, "99")
    await user.click(
      within(digest).getByRole("button", { name: "Save Digest list length" })
    )
    expect(await within(digest).findByRole("alert")).toHaveTextContent(/25/)
  })

  it("shows setting changes and offers no rollback (not built on the server)", async () => {
    renderApp("/settings/history")
    expect(
      await screen.findByText("notifications.quiet_hours_start")
    ).toBeInTheDocument()
    expect(screen.getByText("22:00")).toBeInTheDocument()
    expect(screen.getByTestId("rollback-note")).toHaveTextContent(
      /not available yet/
    )
    expect(screen.queryByRole("button", { name: /Roll back/ })).toBeNull()
  })
})
