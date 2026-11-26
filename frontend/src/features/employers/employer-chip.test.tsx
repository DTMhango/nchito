import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { EmployerChip } from "./employer-chip"

const live = (n: number, elsewhere: number) => ({
  state: "role_in_progress" as const,
  text: `${n} roles in progress`,
  live: n,
  live_elsewhere: elsewhere,
})

describe("EmployerChip on an application", () => {
  it("shows role in progress when another role at the employer is live", () => {
    render(<EmployerChip chip={live(2, 1)} onApplication />)
    expect(screen.getByText("1 other role in progress")).toHaveAttribute(
      "data-employer-state",
      "role_in_progress"
    )
  })

  it("stays quiet when the only live role is this one, or the employer is free", () => {
    const { container, rerender } = render(
      <EmployerChip chip={live(1, 0)} onApplication />
    )
    expect(container).toBeEmptyDOMElement()
    rerender(
      <EmployerChip
        chip={{ state: "free", text: "free to apply" }}
        onApplication
      />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("keeps the server's text elsewhere (Matches)", () => {
    render(<EmployerChip chip={live(2, 2)} />)
    expect(screen.getByText("2 roles in progress")).toBeInTheDocument()
  })
})
