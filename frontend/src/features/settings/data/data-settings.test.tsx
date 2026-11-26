import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import { renderApp, setupUser } from "@/test/render"
import { aiMockState } from "@/mocks/handlers/ai"
import { settingRow } from "@/mocks/dataset/settings"

describe("Settings > Connections", () => {
  it("saves a mailbox without ever showing its password", async () => {
    const user = setupUser()
    renderApp("/settings/connections")
    const form = await screen.findByRole("form", { name: "Add Mailbox" })
    await user.type(
      within(form).getByLabelText("Email address"),
      "me@example.com"
    )
    await user.type(
      within(form).getByLabelText("IMAP server"),
      "imap.example.com"
    )
    await user.type(within(form).getByLabelText(/IMAP port/), "993")
    await user.type(
      within(form).getByLabelText("SMTP server"),
      "smtp.example.com"
    )
    await user.type(within(form).getByLabelText(/SMTP port/), "587")
    const pw = within(form).getByLabelText("App password")
    expect(pw).toHaveAttribute("type", "password")
    await user.type(pw, "hunter2-secret-9876")
    await user.click(
      within(form).getByRole("button", { name: "Connect mailbox" })
    )

    const card = await screen.findByRole("listitem", { name: "Mailbox" })
    expect(
      within(card).getByText(/Saved and hidden: password/)
    ).toBeInTheDocument()
    // Neither the typed secret nor the server's masked form is rendered anywhere.
    expect(document.body.textContent).not.toMatch(/hunter2|9876|\*{4}/)
    // The form cleared the secret field after saving.
    expect(within(form).getByLabelText("App password")).toHaveValue("")
  })

  it("never renders secret values the server returns", async () => {
    aiMockState().connections.push({
      id: "t1",
      created_at: "",
      updated_at: "",
      provider: "telegram",
      label: "Alerts bot",
      config: { chat_id: "123" },
      secrets_masked: { bot_token: "********ZZZZ" },
      scopes_granted: [],
      reads_description: "Nothing. It only sends messages to your chat.",
      health: "ok",
      last_checked_at: null,
      enabled: true,
    })
    renderApp("/settings/connections")
    const card = await screen.findByRole("listitem", { name: "Alerts bot" })
    expect(
      within(card).getByText(/Saved and hidden: bot token/)
    ).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/ZZZZ|\*{4}/)
  })

  it("states in words what Gmail was allowed to do", async () => {
    aiMockState().connections.push({
      id: "g1",
      created_at: "",
      updated_at: "",
      provider: "gmail",
      label: "Job mailbox",
      config: {},
      secrets_masked: {},
      scopes_granted: [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
      ],
      reads_description: "Only the label Jobs.",
      health: "ok",
      last_checked_at: null,
      enabled: true,
    })
    renderApp("/settings/connections")
    const card = await screen.findByRole("listitem", { name: "Job mailbox" })
    expect(within(card).getByText("Send email as you")).toBeInTheDocument()
    expect(
      within(card).getByText(/Read your whole mailbox/)
    ).toBeInTheDocument()
    expect(within(card).getByText("Only the label Jobs.")).toBeInTheDocument()
  })

  it("tests and disconnects a connection after a confirming click", async () => {
    const user = setupUser()
    aiMockState().connections.push({
      id: "w1",
      created_at: "",
      updated_at: "",
      provider: "webhook",
      label: "Hook",
      config: { url: "https://example.com/hook" },
      secrets_masked: {},
      scopes_granted: [],
      reads_description: null,
      health: "unknown",
      last_checked_at: null,
      enabled: true,
    })
    renderApp("/settings/connections")
    const card = await screen.findByRole("listitem", { name: "Hook" })
    await user.click(within(card).getByRole("button", { name: "Test Hook" }))
    expect(await within(card).findByText(/Test passed/)).toBeInTheDocument()
    await user.click(
      within(card).getByRole("button", { name: "Disconnect Hook" })
    )
    await user.click(
      within(card).getByRole("button", { name: /Yes, disconnect/ })
    )
    await waitFor(() =>
      expect(screen.queryByRole("listitem", { name: "Hook" })).toBeNull()
    )
  })
})

describe("Settings > Data", () => {
  it("explains the two exports and checks the template for personal details", async () => {
    const user = setupUser()
    renderApp("/settings/data")
    const backup = await screen.findByRole("article", {
      name: "Personal backup",
    })
    const share = screen.getByRole("article", { name: "Shareable template" })
    expect(
      within(backup).getByText(/Everything: your facts/)
    ).toBeInTheDocument()
    expect(
      within(share).getByText(/No facts, no documents, no history/)
    ).toBeInTheDocument()
    expect(
      within(share).getByRole("button", { name: /Create file/ })
    ).toBeDisabled()
    await user.click(
      within(share).getByRole("button", { name: "See what is inside" })
    )
    expect(
      await within(share).findByText(/1 personal detail found/)
    ).toBeInTheDocument()
    expect(within(share).getByText(/chanda@example.com/)).toBeInTheDocument()
  })

  it("runs a backup and shows the last one", async () => {
    const user = setupUser()
    renderApp("/settings/data")
    await screen.findByText(/Last backup:/)
    const kept = () =>
      within(screen.getByRole("list", { name: "Backups kept" })).getAllByRole(
        "listitem"
      ).length
    await waitFor(() => expect(kept()).toBe(2))
    await user.click(screen.getByRole("button", { name: "Back up now" }))
    await waitFor(() => expect(kept()).toBe(3))
    expect(screen.getByText("How to restore")).toBeInTheDocument()
  })

  it("offers OneDrive and S3 as the backup target", async () => {
    const user = setupUser()
    renderApp("/settings/data")
    const target = await screen.findByRole("combobox", {
      name: "Backup target",
    })
    const options = within(target)
      .getAllByRole("option")
      .map((o) => o.getAttribute("value"))
    expect(options).toEqual(
      expect.arrayContaining(["local", "s3", "gdrive", "onedrive"])
    )
    await user.selectOptions(target, "onedrive")
    await user.click(screen.getByRole("button", { name: "Save Backup target" }))
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Backup target" })
      ).toHaveValue("onedrive")
    )
    await waitFor(() =>
      expect(settingRow("backups.target")?.value).toBe("onedrive")
    )
  })
})

describe("Settings > Notifications and health", () => {
  it("warns when a chosen channel is not connected", async () => {
    renderApp("/settings/notifications")
    await screen.findByRole("heading", { name: "Notifications" })
    const status = await screen.findByRole("list", { name: "Channel status" })
    expect(within(status).getAllByText("Not connected")).toHaveLength(3)
    // The settings blocks render after the settings query; the channel list does not wait.
    expect(
      await screen.findByRole("list", { name: "Quiet hours" })
    ).toBeInTheDocument()
  })

  it("shows each component from the detailed health check", async () => {
    renderApp("/settings/health")
    const list = await screen.findByRole("list", { name: "Health checks" })
    expect(within(list).getAllByRole("listitem")).toHaveLength(6)
    expect(within(list).getByText("Worker")).toBeInTheDocument()
    expect(within(list).getByText("Last backup")).toBeInTheDocument()
    expect(screen.getByTestId("queue")).toHaveTextContent(
      "3 waiting, 1 running, 0 failed"
    )
  })
})
