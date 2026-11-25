import { useState } from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { FilterChip, nextFilterState, type FilterState } from "./chip"

function Harness({ initial = "off" as FilterState }) {
  const [state, setState] = useState<FilterState>(initial)
  return (
    <FilterChip
      facet="Visa sponsorship"
      label="Not stated"
      state={state}
      onStateChange={setState}
    />
  )
}

describe("FilterChip (three-state)", () => {
  it("cycles include, exclude, off", () => {
    expect(nextFilterState("off")).toBe("include")
    expect(nextFilterState("include")).toBe("exclude")
    expect(nextFilterState("exclude")).toBe("off")
  })

  it("cycles on click and announces each state", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const chip = screen.getByRole("button")
    expect(chip).toHaveAttribute("data-state", "off")
    expect(chip).toHaveAccessibleName(/Visa sponsorship: not filtering/)

    await user.click(chip)
    expect(chip).toHaveAttribute("data-state", "include")
    expect(chip).toHaveAccessibleName(/included/)

    await user.click(chip)
    expect(chip).toHaveAttribute("data-state", "exclude")
    expect(chip).toHaveAccessibleName(/excluded/)

    await user.click(chip)
    expect(chip).toHaveAttribute("data-state", "off")
  })

  it("works from the keyboard, and Delete clears", async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.tab()
    await user.keyboard("{Enter}")
    expect(screen.getByRole("button")).toHaveAttribute("data-state", "include")
    await user.keyboard(" ")
    expect(screen.getByRole("button")).toHaveAttribute("data-state", "exclude")
    await user.keyboard("{Delete}")
    expect(screen.getByRole("button")).toHaveAttribute("data-state", "off")
  })

  it("treats Not stated as a value that can be excluded", async () => {
    render(<Harness initial="exclude" />)
    expect(screen.getByRole("button")).toHaveTextContent("Not stated")
    expect(screen.getByRole("button")).toHaveAttribute("data-state", "exclude")
  })
})
