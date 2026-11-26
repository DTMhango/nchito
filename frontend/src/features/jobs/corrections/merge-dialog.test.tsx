import { describe, expect, it } from "vitest"
import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithTheme } from "@/test/render"
import { matchesMock } from "@/mocks/handlers/matches"
import { MergeDialog, mergePreview } from "./merge-dialog"

const jobs = () => matchesMock.get().jobs
const byEmployer = (e: string) => jobs().find((j) => j.employer === e)!

describe("mergePreview", () => {
  it("counts links once and lists added tags", () => {
    const keep = byEmployer("Kafue Analytics")
    const dupe = {
      ...keep,
      id: "dupe",
      tags: ["reinsurance"],
      sightings: [
        keep.sightings[0],
        { ...keep.sightings[0], url: "https://jobs.example.com/a" },
        { ...keep.sightings[0], url: "https://jobs.example.com/b" },
      ],
    }
    const p = mergePreview(keep, [dupe])
    expect(p.sightings).toBe(keep.sightings.length + 2)
    expect(p.addedSightings).toBe(2)
    expect(p.addedTags).toEqual(["reinsurance"])
  })
})

describe("MergeDialog", () => {
  it("searches, previews what is kept, and merges", async () => {
    const user = userEvent.setup()
    const keep = byEmployer("Kafue Analytics")
    renderWithTheme(<MergeDialog job={keep} open onOpenChange={() => {}} />)
    const dialog = screen.getByRole("dialog")
    const merge = within(dialog).getByRole("button", {
      name: /Merge into this role/,
    })
    expect(merge).toBeDisabled()

    await user.type(
      within(dialog).getByLabelText("Search roles"),
      "Mulungushi Digital"
    )
    const pick = await within(dialog).findByRole("checkbox")
    await user.click(pick)

    const preview = await within(dialog).findByRole("region", {
      name: "What will be kept",
    })
    expect(preview).toHaveTextContent(keep.title)
    expect(preview).toHaveTextContent("2 in all (1 added)")
    expect(merge).toBeEnabled()
  })

  it("does not offer the role itself", async () => {
    const user = userEvent.setup()
    const keep = byEmployer("Kafue Analytics")
    renderWithTheme(<MergeDialog job={keep} open onOpenChange={() => {}} />)
    await user.type(screen.getByLabelText("Search roles"), "Kafue Analytics")
    expect(
      await screen.findByText(/no other roles|nothing found|no roles/i)
    ).toBeInTheDocument()
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0)
  })
})
