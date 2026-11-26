import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import { aiMockState } from "@/mocks/handlers/ai"
import { dataMock } from "@/mocks/handlers/data"
import { settingValues } from "@/mocks/dataset/settings"
import { renderApp, setupUser } from "@/test/render"
import { MICROSOFT_NOT_SET_UP } from "./connect-form"

type Conn = ReturnType<typeof aiMockState>["connections"][number]

const conn = (over: Partial<Conn>): Conn => ({
  id: crypto.randomUUID(),
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  provider: "msgraph",
  label: "Outlook (owner.jobs@example.com)",
  config: { from_address: "owner.jobs@example.com" },
  secrets_masked: { refresh_token: "********abcd" },
  scopes_granted: ["offline_access", "User.Read", "Mail.Send", "Mail.Read"],
  reads_description: "Reads only the folder you choose.",
  health: "unknown",
  last_checked_at: null,
  enabled: true,
  ...over,
})

async function open(name: string) {
  const user = setupUser()
  renderApp("/settings/connections")
  const section = await screen.findByRole("region", { name })
  return { user, section }
}

describe("Outlook and OneDrive connections", () => {
  it("says what to set on the server when Microsoft sign-in is not configured", async () => {
    dataMock.microsoftConfigured = false
    const { user, section } = await open("Outlook")
    await user.click(
      within(section).getByRole("button", { name: "Connect Outlook" })
    )
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      MICROSOFT_NOT_SET_UP
    )
    expect(MICROSOFT_NOT_SET_UP).toMatch(
      /MS_OAUTH_CLIENT_ID and MS_OAUTH_CLIENT_SECRET/
    )
  })

  it("shows the permissions in plain words and never a secret, and changes the folder", async () => {
    aiMockState().connections.push(conn({}))
    const { user, section } = await open("Outlook")
    const card = await within(section).findByRole("listitem", {
      name: "Outlook (owner.jobs@example.com)",
    })
    expect(
      within(card).getByText(/Read your whole mailbox \(Outlook cannot/)
    ).toBeInTheDocument()
    expect(within(card).getByText("Send email as you")).toBeInTheDocument()
    expect(within(card).queryByText("Mail.Send")).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain("abcd")
    await user.click(
      within(card).getByRole("button", {
        name: "Change Outlook (owner.jobs@example.com)",
      })
    )
    const form = within(section).getByRole("form", {
      name: "Change Outlook (owner.jobs@example.com)",
    })
    await user.type(within(form).getByLabelText(/Folder to read/), "Jobs")
    await user.click(within(form).getByRole("button", { name: "Save changes" }))
    await waitFor(() =>
      expect(aiMockState().connections[0].config.read_folder).toBe("Jobs")
    )
    expect(aiMockState().connections[0].config.from_address).toBe(
      "owner.jobs@example.com"
    )
  })

  it("tests and disconnects OneDrive", async () => {
    aiMockState().connections.push(
      conn({
        provider: "onedrive",
        label: "OneDrive",
        config: {},
        secrets_masked: { tokens: "********" },
        scopes_granted: [
          "offline_access",
          "User.Read",
          "Files.ReadWrite.AppFolder",
        ],
      })
    )
    const { user, section } = await open("OneDrive")
    const card = await within(section).findByRole("listitem", {
      name: "OneDrive",
    })
    expect(
      within(card).getByText(/only the files this app puts in its own OneDrive/)
    ).toBeInTheDocument()
    expect(
      within(card).queryByRole("button", { name: /^Change/ })
    ).not.toBeInTheDocument()
    await user.click(
      within(card).getByRole("button", { name: "Test OneDrive" })
    )
    expect(await within(section).findByRole("status")).toHaveTextContent(
      "Test passed"
    )
    await user.click(
      within(card).getByRole("button", { name: "Disconnect OneDrive" })
    )
    await user.click(
      within(card).getByRole("button", { name: "Yes, disconnect OneDrive" })
    )
    await waitFor(() => expect(aiMockState().connections).toHaveLength(0))
  })

  it("offers no default choice with a single mailbox", async () => {
    aiMockState().connections.push(conn({}))
    const { section } = await open("Outlook")
    await within(section).findByRole("listitem", {
      name: "Outlook (owner.jobs@example.com)",
    })
    expect(
      screen.queryByRole("button", { name: /as the default mailbox/ })
    ).not.toBeInTheDocument()
    expect(screen.queryByText("Default mailbox")).not.toBeInTheDocument()
  })

  it("lets the owner pick the default mailbox when more than one is connected", async () => {
    const outlook = conn({ created_at: "2026-11-02T00:00:00Z" })
    aiMockState().connections.push(
      conn({
        provider: "gmail",
        label: "Gmail (me@example.com)",
        created_at: "2026-11-01T00:00:00Z",
        config: { from_address: "me@example.com" },
        scopes_granted: [],
      }),
      outlook
    )
    const { user, section } = await open("Outlook")
    const card = await within(section).findByRole("listitem", {
      name: outlook.label,
    })
    // Nothing chosen yet: the mailbox connected first is the default.
    expect(
      screen.getByRole("listitem", { name: "Gmail (me@example.com)" })
    ).toHaveTextContent("Default mailbox")
    await user.click(
      await within(card).findByRole("button", {
        name: `Use ${outlook.label} as the default mailbox`,
      })
    )
    await waitFor(() =>
      expect(settingValues["mail.default_mailbox"]).toBe(outlook.id)
    )
    expect(await within(card).findByText("Default mailbox")).toBeInTheDocument()
  })

  it("lets the owner send backups to OneDrive when Drive is connected too", async () => {
    aiMockState().connections.push(
      conn({ provider: "gdrive", label: "Google Drive", scopes_granted: [] }),
      conn({
        provider: "onedrive",
        label: "OneDrive",
        scopes_granted: [],
        created_at: "2026-11-03T00:00:00Z",
      })
    )
    const { user, section } = await open("OneDrive")
    await user.click(
      await within(section).findByRole("button", {
        name: "Use OneDrive for backups",
      })
    )
    await waitFor(() =>
      expect(settingValues["backups.target"]).toBe("onedrive")
    )
    expect(
      await within(section).findByText("Backups go here")
    ).toBeInTheDocument()
  })
})
