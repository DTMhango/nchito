import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api/client"
import { prepareBody, sendError } from "./packet"

describe("prepare", () => {
  it("sends the picked templates and the channel, and leaves an unpicked one to the server", () => {
    expect(prepareBody({ cv: "compact", letter: "" }, "manual")).toEqual({
      channel: "manual",
      cv_template: "compact",
      letter_template: null,
    })
  })
  it("reads a refusal by its code, whatever the words", () => {
    const stale = sendError(
      new ApiError(409, {
        detail: { code: "check_stale", reason: "anything at all" },
      })
    )
    expect(stale).toMatchObject({
      code: "check_stale",
      action: "recheck",
      reason: "anything at all",
    })
    const gone = sendError(
      new ApiError(409, {
        detail: { code: "illegal_stage", reason: "cannot be repacked" },
      })
    )
    expect(gone.text).toMatch(/already moved on/)
    expect(gone.action).toBeNull()
  })
})
