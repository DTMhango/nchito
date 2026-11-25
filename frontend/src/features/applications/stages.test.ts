import { describe, expect, it } from "vitest"
import { checkMove, columnOf } from "./stages"

describe("checkMove", () => {
  it("allows ordinary forward and back moves before submission", () => {
    expect(checkMove("shortlisted", "tailoring")).toEqual({
      kind: "stage",
      stage: "tailoring",
    })
    expect(checkMove("tailoring", "shortlisted")).toEqual({
      kind: "stage",
      stage: "shortlisted",
    })
  })

  it("never marks submitted: it routes to I applied myself", () => {
    for (const from of [
      "shortlisted",
      "tailoring",
      "ready",
      "submitted_unconfirmed",
    ] as const)
      expect(checkMove(from, "submitted")).toEqual({ kind: "applied-myself" })
  })

  it("refuses runner-owned stages and explains why", () => {
    expect(checkMove("ready", "applying")).toMatchObject({ kind: "refused" })
    expect(checkMove("ready", "submitted_unconfirmed")).toMatchObject({
      kind: "refused",
    })
    expect(checkMove("applying", "ready")).toMatchObject({ kind: "refused" })
  })

  it("refuses skipping Applied, going back after submission, and reaching Ready by hand", () => {
    expect(checkMove("tailoring", "interview")).toMatchObject({
      kind: "refused",
    })
    expect(checkMove("interview", "tailoring")).toMatchObject({
      kind: "refused",
    })
    expect(checkMove("screening", "submitted")).toMatchObject({
      kind: "refused",
    })
    expect(checkMove("tailoring", "ready")).toMatchObject({ kind: "refused" })
    expect(checkMove("shortlisted", "ready")).toMatchObject({ kind: "refused" })
  })

  it("moves forward after submission and reopens closed roles only to Shortlisted", () => {
    expect(checkMove("submitted", "interview")).toEqual({
      kind: "stage",
      stage: "interview",
    })
    expect(checkMove("interview", "closed")).toEqual({
      kind: "stage",
      stage: "closed",
    })
    expect(checkMove("closed", "shortlisted")).toMatchObject({ kind: "stage" })
    expect(checkMove("closed", "interview")).toMatchObject({ kind: "refused" })
  })

  it("groups end states in Closed and accepted with Offer", () => {
    expect(columnOf("rejected")).toBe("closed")
    expect(columnOf("accepted")).toBe("offer")
  })
})
