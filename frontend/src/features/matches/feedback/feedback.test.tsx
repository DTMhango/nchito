import { describe, expect, it } from "vitest"
import { screen, waitFor, within } from "@testing-library/react"
import { renderApp, setupUser } from "@/test/render"
import { preferencesMock } from "@/mocks/handlers/preferences"
import { matchesMock } from "@/mocks/handlers/matches"

const section = () => screen.getByRole("region", { name: "Your feedback" })

describe("feedback on a role", () => {
  it("saves a thumbs down with reasons and a note, then withdraws it", async () => {
    renderApp("/matches")
    await screen.findByRole("heading", { level: 2, name: "Analytics Lead" })
    await screen.findByRole("region", { name: "Your feedback" })
    expect(section()).toHaveTextContent(
      "Feedback is kept as evidence. It never changes a score by itself; suggestions you approve do."
    )
    const user = setupUser()
    const down = within(section()).getByRole("button", { name: "Thumbs down" })
    const up = within(section()).getByRole("button", { name: "Thumbs up" })
    expect(down).toHaveAttribute("aria-pressed", "false")
    const save = within(section()).getByRole("button", {
      name: "Save feedback",
    })
    expect(save).toBeDisabled()

    await user.click(down)
    expect(down).toHaveAttribute("aria-pressed", "true")
    expect(up).toHaveAttribute("aria-pressed", "false")
    await user.click(
      within(section()).getByRole("button", { name: "Too junior" })
    )
    await user.click(within(section()).getByRole("button", { name: "Pay" }))
    expect(
      within(section()).getByRole("button", { name: "Pay" })
    ).toHaveAttribute("aria-pressed", "true")
    await user.type(
      within(section()).getByRole("textbox", { name: "Note (optional)" }),
      "Graduate level role."
    )
    await user.click(save)

    await within(section()).findByText("Saved: thumbs down, Too junior, Pay.")
    const job = matchesMock
      .get()
      .jobs.find((j) => j.title === "Analytics Lead")!
    const sent = preferencesMock.get().requests.feedback.at(-1)!
    expect(sent).toMatchObject({
      verdict: "down",
      reasons: ["too_junior", "pay"],
      note: "Graduate level role.",
    })
    expect(sent.campaign_id).toBeTruthy()
    expect(preferencesMock.get().feedback).toHaveLength(1)
    expect(preferencesMock.get().feedback[0].job_id).toBe(job.id)

    await user.click(
      within(section()).getByRole("button", { name: "Withdraw" })
    )
    await waitFor(() => expect(preferencesMock.get().feedback).toHaveLength(0))
    await waitFor(() =>
      expect(
        within(section()).getByRole("button", { name: "Thumbs down" })
      ).toHaveAttribute("aria-pressed", "false")
    )
    expect(
      within(section()).queryByRole("button", { name: "Withdraw" })
    ).not.toBeInTheDocument()
  })

  it("shows the server's message when the note is too long", async () => {
    renderApp("/matches")
    await screen.findByRole("heading", { level: 2, name: "Analytics Lead" })
    await screen.findByRole("region", { name: "Your feedback" })
    const user = setupUser()
    await user.click(
      within(section()).getByRole("button", { name: "Thumbs up" })
    )
    const note = within(section()).getByRole("textbox", {
      name: "Note (optional)",
    })
    await user.click(note)
    await user.paste("x".repeat(501))
    await user.click(
      within(section()).getByRole("button", { name: "Save feedback" })
    )
    expect(await within(section()).findByRole("alert")).toHaveTextContent(
      "Keep the note to 500 characters or fewer."
    )
  })
})
