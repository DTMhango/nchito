import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api/client"
import type { Schemas } from "@/lib/api/types"
import type { DraftAnswer } from "./api"
import { packetAnswers, sendError, sendingIdentity } from "./packet"

const answer = (o: Partial<DraftAnswer>): DraftAnswer => ({
  question: "Q",
  outcome: "value",
  value: "One month",
  select: null,
  answer_id: null,
  material: false,
  reason: "",
  pending_action_id: null,
  ...o,
})
const mailbox = (o: Partial<Schemas["ConnectionOut"]>) =>
  ({
    provider: "imap_smtp",
    enabled: true,
    config: { from_address: "jobs@example.com" },
    ...o,
  }) as Schemas["ConnectionOut"]

describe("packet build", () => {
  it("sends only answers with a value, by bank id when there is one", () => {
    expect(
      packetAnswers([
        answer({ question: "A", answer_id: "an-1" }),
        answer({ question: "B" }),
        answer({ question: "C", outcome: "ask_owner", value: "Yes" }),
        answer({ question: "D", outcome: "do_not_answer" }),
      ])
    ).toEqual([
      { question: "A", answer_id: "an-1" },
      { question: "B", value: "One month" },
    ])
  })
  it("sends as the connected mailbox, else the owner's address", () => {
    expect(sendingIdentity([mailbox({})], "me@example.com")).toBe(
      "jobs@example.com"
    )
    expect(
      sendingIdentity(
        [mailbox({ enabled: false }), mailbox({ provider: "anthropic" })],
        "me@example.com"
      )
    ).toBe("me@example.com")
    expect(sendingIdentity([], undefined)).toBeNull()
  })
  it("says plainly when the application has already gone out", () => {
    const gone = sendError(
      new ApiError(409, {
        detail: "an application in submitted cannot be repacked",
      })
    )
    expect(gone).toEqual({
      text: expect.stringMatching(/already gone out/),
      recheck: false,
    })
    const stale = sendError(new ApiError(409, { detail: "spec not checked" }))
    expect(stale.recheck).toBe(true)
  })
})
