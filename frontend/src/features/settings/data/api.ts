/** Settings > Data: export, import, backups, retention. Typed from the generated contract. */
import { queryOptions } from "@tanstack/react-query"
import { api, ApiError, toFormData, unwrap } from "@/lib/api/client"
import type { components } from "@/lib/api/types"

type S = components["schemas"]
export type ExportKind = S["ExportIn"]["kind"]
export type ExportPreview = S["ExportPreviewOut"]
export type ExportResult = S["ExportOut"]
export type ImportSource = S["Body_data_import_preview"]["source"]
export type ImportPreview = S["app__api__routers__data__ImportPreviewOut"]
export type ImportDiffItem = S["ImportDiffItem"]
export type ImportCommit = S["ImportCommitOut"]
export type Backup = S["BackupOut"]
export type HealthDetail = S["DetailedHealth"]
export type HealthComponent = S["Component"]
export type PersonalDetailHit = S["PersonalDetailHit"]

export const dataKeys = {
  backups: ["data", "backups"] as const,
  health: ["health", "detail"] as const,
}

export const exportPreview = (kind: ExportKind) =>
  unwrap(api.POST("/api/data/export/preview", { body: { kind } }))
/** A share setup with personal details answers 409 until `acknowledge` is true. */
export const exportKit = (kind: ExportKind, acknowledge = false) =>
  unwrap(
    api.POST("/api/data/export", {
      body: { kind, acknowledge_personal_details: acknowledge },
    })
  )

/**
 * Fetch a prepared export (`download_url`, `GET /api/data/exports/{id}`) and hand it to the
 * browser as a file. A 404 means the link has expired (`data.export_link_minutes`).
 */
export async function downloadExport(file: ExportResult): Promise<void> {
  const res = await fetch(new URL(file.download_url, window.location.origin), {
    credentials: "include",
  })
  if (res.status === 404)
    throw new ApiError(404, {
      detail: "This file has expired. Create it again.",
    })
  if (!res.ok) throw new ApiError(res.status, undefined)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement("a")
  a.href = url
  a.download = file.file_name
  a.click()
  URL.revokeObjectURL(url)
}

/** Upload a file and get the diff back. Nothing is written until `commitImport`. */
export const previewImport = (file: File, source: ImportSource) =>
  unwrap(
    api.POST("/api/data/import", {
      body: { file: file as unknown as string, source },
      bodySerializer: toFormData,
    })
  ) as unknown as Promise<ImportPreview>

export const commitImport = (import_id: string, exclude_keys: string[]) =>
  unwrap(
    api.POST("/api/data/import/commit", { body: { import_id, exclude_keys } })
  )

export const backupsQuery = () =>
  queryOptions({
    queryKey: dataKeys.backups,
    queryFn: () => unwrap(api.GET("/api/data/backups")),
  })
export const runBackup = () =>
  unwrap(api.POST("/api/data/backups")) as unknown as Promise<Backup>
export const runRetention = () => unwrap(api.POST("/api/data/retention/run"))

export const healthQuery = () =>
  queryOptions({
    queryKey: dataKeys.health,
    queryFn: () => unwrap(api.GET("/api/health/detail")),
    refetchInterval: 30_000,
  })
