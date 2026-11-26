import { beforeEach, describe, expect, it } from "vitest"
import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithTheme } from "@/test/render"
import { buildJobs } from "@/mocks/fixtures/jobs"
import { resetJobsMock } from "@/mocks/handlers/jobs"
import { MergeDialog, mergePreview } from "./merge-dialog"

beforeEach(() => resetJobsMock())

describe("mergePreview", () => {
  it("counts links once and lists added tags", () => {
    const [keep, , dupe] = buildJobs()
    const p = mergePreview(keep, [dupe])
    expect(p.sightings).toBe(4)
    expect(p.addedSightings).toBe(2)
    expect(p.addedTags).toEqual(["reinsurance"])
  })
})

describe("MergeDialog", () => {
  it("searches, previews what is kept, and merges", async () => {
    const user = userEvent.setup()
    const keep = buildJobs()[0]
    renderWithTheme(<MergeDialog job={keep} open onOpenChange={() => {}} />)
    const dialog = screen.getByRole("dialog")
    const merge = within(dialog).getByRole("button", { name: /Merge into this role/ })
    expect(merge).toBeDisabled()

    await user.type(within(dialog).getByLabelText("Search roles"), "Actuarial")
    const pick = await within(dialog).findByRole("checkbox")
    await user.click(pick)

    const preview = await within(dialog).findByRole("region", {
      name: "What will be kept",
    })
    expect(preview).toHaveTextContent("Senior Risk Analyst")
    expect(preview).toHaveTextContent("4 in all (2 added)")
    expect(preview).toHaveTextContent("added: reinsurance")
    expect(merge).toBeEnabled()
  })

  it("does not offer the role itself", async () => {
    const user = userEvent.setup()
    const keep = buildJobs()[0]
    renderWithTheme(<MergeDialog job={keep} open onOpenChange={() => {}} />)
    await user.type(screen.getByLabelText("Search roles"), "Risk")
    // job-2 matches, job-1 (this role) must not be listed
    expect(await screen.findByText(/Risk Analyst/)).toBeInTheDocument()
    expect(screen.getAllByRole("checkbox")).toHaveLength(1)
  })
})
