/** Typed calls for messages, the follow-up due list and the wind-down (generated contract). */
import { queryOptions } from "@tanstack/react-query"
import { api, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]

export type MessageOut = S["MessageOut"]
export type MessagesOut = S["MessagesOut"]
export type MessageKind = S["MessageCreateIn"]["kind"]
export type MessageCreateIn = S["MessageCreateIn"]
export type MessageEditIn = S["MessageEditIn"]
export type MessageSendOut = S["MessageSendOut"]
export type FollowupItem = S["FollowupItemOut"]
export type FollowupList = S["FollowupListOut"]
export type WindDownOut = S["WindDownOut"]
export type WindDownItem = S["WindDownItemOut"]
export type WindDownChoice = S["WindDownChoiceIn"]["choice"]

export const followupKeys = {
  messages: (appId: string) => ["messages", appId] as const,
  due: ["follow-ups"] as const,
  windDown: ["wind-down"] as const,
}

export const KIND_LABEL: Record<MessageKind, string> = {
  follow_up: "Follow-up",
  thank_you: "Thank-you",
  info_reply: "Reply with information",
  slot_accept: "Accept the interview slot",
  slot_decline: "Decline the interview slot",
  withdraw: "Withdraw the application",
  offer_decline: "Decline the offer",
}

export const messagesQuery = (appId: string) =>
  queryOptions({
    queryKey: followupKeys.messages(appId),
    queryFn: () =>
      unwrap(
        api.GET("/api/applications/{application_id}/messages", {
          params: { path: { application_id: appId } },
        })
      ),
  })

export const createMessage = (appId: string, body: MessageCreateIn) =>
  unwrap(
    api.POST("/api/applications/{application_id}/messages", {
      params: { path: { application_id: appId } },
      body,
    })
  )

export const editMessage = (id: string, body: MessageEditIn) =>
  unwrap(
    api.PUT("/api/messages/{message_id}", {
      params: { path: { message_id: id } },
      body,
    })
  )

type Action = "approve" | "cancel" | "discard" | "regenerate" | "check"

export const messageAction = (id: string, action: Action) => {
  const path = { params: { path: { message_id: id } } }
  switch (action) {
    case "approve":
      return unwrap(api.POST("/api/messages/{message_id}/approve", path))
    case "cancel":
      return unwrap(api.POST("/api/messages/{message_id}/cancel", path))
    case "discard":
      return unwrap(api.POST("/api/messages/{message_id}/discard", path))
    case "regenerate":
      return unwrap(api.POST("/api/messages/{message_id}/regenerate", path))
    case "check":
      return unwrap(api.POST("/api/messages/{message_id}/check", path))
  }
}

export const sendMessage = (id: string) =>
  unwrap(
    api.POST("/api/messages/{message_id}/send", {
      params: { path: { message_id: id } },
    })
  )

export const followupsQuery = () =>
  queryOptions({
    queryKey: followupKeys.due,
    queryFn: () => unwrap(api.GET("/api/follow-ups")),
  })

export const draftFollowup = (appId: string) =>
  unwrap(
    api.POST("/api/follow-ups/{application_id}/draft", {
      params: { path: { application_id: appId } },
    })
  )

export const snoozeFollowup = (appId: string) =>
  unwrap(
    api.POST("/api/follow-ups/{application_id}/snooze", {
      params: { path: { application_id: appId } },
      body: {},
    })
  )

export const followupNotNeeded = (appId: string) =>
  unwrap(
    api.POST("/api/follow-ups/{application_id}/not-needed", {
      params: { path: { application_id: appId } },
    })
  )

export const windDownQuery = () =>
  queryOptions({
    queryKey: followupKeys.windDown,
    queryFn: () => unwrap(api.GET("/api/wind-down")),
  })

export const startWindDown = (reason: string | null) =>
  unwrap(api.POST("/api/wind-down", { body: { reason } }))

export const chooseWindDown = (key: string, choice: WindDownChoice) =>
  unwrap(api.POST("/api/wind-down/choices", { body: { key, choice } }))

export const reopenWindDown = () => unwrap(api.POST("/api/wind-down/reopen"))

export const WIND_DOWN_SUMMARY_URL = "/api/wind-down/summary"
