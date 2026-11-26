import { describe, expect, it } from "vitest"
import { configure, screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { renderWithTheme, setupUser } from "@/test/render"
import { server } from "@/test/server"
import { mockInterviewMock } from "@/mocks/handlers/mock-interview"
import { MockInterviewPanel } from "./panel"

configure({ asyncUtilTimeout: 6000 })
const JOB = "job-mock-1"

async function openSession(user: ReturnType<typeof setupUser>, status: string) {
  renderWithTheme(<MockInterviewPanel jobId={JOB} />)
  const row = await waitFor(() => {
    const found = [
      ...document.querySelectorAll<HTMLElement>("[data-history]"),
    ].find((r) => within(r).queryByText(status))
    if (!found) throw new Error(`no ${status} session yet`)
    return found
  })
  await user.click(within(row).getByRole("button", { name: "Open" }))
}

describe("mock interview", () => {
  it("shows a claim removed by the truth checks, flagged, next to the kept suggestion", async () => {
    const user = setupUser()
    await openSession(user, "done")
    expect(
      await screen.findByRole("region", { name: "Feedback" })
    ).toBeInTheDocument()
    const flagged = document.querySelector("[data-flagged-claim]")!
    expect(flagged).toHaveTextContent(
      "I led a team of 12 analysts on the sales pack."
    )
    expect(flagged).toHaveTextContent("figure '12' is not in the cited facts")
    expect(screen.getByText(/Removed from the suggestion/)).toBeInTheDocument()
    expect(document.querySelector('[data-fact="F-1"]')).toBeInTheDocument()
    expect(document.querySelector('[data-your-words="A2"]')).toHaveTextContent(
      "Your words A2"
    )
  })

  it("asks before treating an unverified statement as a fact", async () => {
    const user = setupUser()
    let called = ""
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/claims/")) called = request.url
    })
    await openSession(user, "done")
    expect(
      await screen.findByText(
        "Is this accurate? Add it to your library as a draft fact?"
      )
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Add as draft fact" }))
    expect(
      await screen.findByText(/Added to your library as draft F-90/)
    ).toBeInTheDocument()
    expect(called).toMatch(/\/claims\/c1$/)
    server.events.removeAllListeners()
  })

  it("shows the paused state and resumes the chat", async () => {
    const user = setupUser()
    await openSession(user, "paused")
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(
      "Paused: the AI budget for this session is used up"
    )
    await user.click(within(alert).getByRole("button", { name: "Resume" }))
    // The interviewer's next question arrives and the composer is back.
    expect(
      await screen.findByText("How would you approach our reporting backlog?", {
        selector: "p",
      })
    ).toBeInTheDocument()
    expect(
      await screen.findByRole("textbox", { name: /Your answer/ })
    ).toBeInTheDocument()
    expect(document.querySelector("[data-paused]")).toBeNull()
  })

  it("shows the estimate before starting, then sends answers with the expected turn key", async () => {
    const user = setupUser()
    const keys: (string | null)[] = []
    server.use(
      http.post(
        "*/api/interview-mock/:id/answer",
        async ({ request, params }) => {
          const body = (await request.json()) as { turn_key: string | null }
          keys.push(body.turn_key)
          return HttpResponse.json(mockInterviewMock.get(String(params.id)))
        }
      )
    )
    renderWithTheme(<MockInterviewPanel jobId={JOB} />)
    await user.click(
      await screen.findByRole("button", { name: "New mock interview" })
    )
    expect(await screen.findByText(/At most/)).toHaveTextContent(
      "it pauses and asks you past"
    )
    await user.click(
      screen.getByRole("button", { name: "Start the interview" })
    )
    const box = await screen.findByRole("textbox", { name: /Your answer/ })
    await waitFor(() => expect(box).toHaveFocus())
    await user.type(box, "I automated the sales pack.")
    await user.keyboard("{Control>}{Enter}{/Control}")
    await waitFor(() => expect(keys).toEqual(["a0.0"]))
  })

  it("lists progress and what to practise next", async () => {
    renderWithTheme(<MockInterviewPanel jobId={JOB} />)
    expect(await screen.findByText("Practise these next")).toBeInTheDocument()
    expect(screen.getByText(/behavioural: 2.8/)).toBeInTheDocument()
  })
})
