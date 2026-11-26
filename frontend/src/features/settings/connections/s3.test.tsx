import { describe, expect, it } from "vitest"
import { screen, within } from "@testing-library/react"
import { aiMockState } from "@/mocks/handlers/ai"
import { renderApp, setupUser } from "@/test/render"

const SECRET = "s3cr3t-access-value-9876"

describe("S3 backup storage connection", () => {
  it("saves the address and bucket as config and both keys as write-only secrets", async () => {
    const user = setupUser()
    renderApp("/settings/connections")
    const section = await screen.findByRole("region", {
      name: "Backup storage (S3-compatible)",
    })
    const form = within(section).getByRole("form", {
      name: "Add Backup storage",
    })
    await user.type(
      within(form).getByLabelText("Storage address"),
      "https://s3.example.com"
    )
    await user.type(within(form).getByLabelText("Bucket"), "nchito-backups")
    await user.type(within(form).getByLabelText("Access key ID"), "AKIAEXAMPLE")
    await user.type(within(form).getByLabelText("Secret access key"), SECRET)
    await user.click(
      within(form).getByRole("button", { name: "Connect storage" })
    )
    await within(section).findByRole("listitem", { name: "Backup storage" })
    const saved = aiMockState().connections.find((c) => c.provider === "s3")!
    expect(saved.config).toEqual({
      endpoint: "https://s3.example.com",
      bucket: "nchito-backups",
    })
    expect(document.body.textContent).not.toContain(SECRET)
  })
})
