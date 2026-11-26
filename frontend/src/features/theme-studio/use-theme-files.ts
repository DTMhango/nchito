import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { toast } from "sonner"
import { isApiError } from "@/lib/api/client"
import {
  duplicateTheme,
  importThemeFile,
  invalidateThemes,
  settingValueQuery,
  studioKeys,
  type LowContrastPair,
} from "./api"

/** The low-contrast pairs of a coded 422, or null for any other error. */
export function lowContrastPairs(e: unknown): LowContrastPair[] | null {
  if (!isApiError(e, 422)) return null
  const d = e.body?.detail
  if (
    d &&
    !Array.isArray(d) &&
    typeof d === "object" &&
    d.code === "theme_low_contrast"
  )
    return (d.pairs as LowContrastPair[]) ?? []
  return null
}

/**
 * Import a theme file (untrusted: size-checked here against `themes.import_max_bytes`, then
 * validated strictly by the server) and build-your-own (duplicate, then open in the studio).
 */
export function useThemeFiles() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const limit = useQuery(settingValueQuery("themes.import_max_bytes"))
  const maxBytes = typeof limit.data === "number" ? limit.data : null

  const open = async (id: string) => {
    await qc.invalidateQueries({ queryKey: studioKeys.themes })
    invalidateThemes(qc)
    void navigate({ to: "/theme-studio/$themeId", params: { themeId: id } })
  }

  async function importFile(file: File) {
    if (maxBytes === null) {
      toast.error(
        "Couldn't read the theme file size limit. Try again in a moment."
      )
      return
    }
    if (file.size > maxBytes) {
      toast.error(
        `That file is ${Math.ceil(file.size / 1024)} KB; theme files can be at most ${Math.floor(maxBytes / 1024)} KB.`
      )
      return
    }
    const text = await file.text()
    try {
      const t = await importThemeFile(text, false)
      toast.success(`Imported ${t.name}.`)
      await open(t.id)
    } catch (e) {
      const pairs = lowContrastPairs(e)
      if (pairs) {
        const list = pairs
          .map((p) => `${p.fg} on ${p.bg} (${p.mode}, ${p.ratio}:1)`)
          .join(", ")
        if (
          window.confirm(
            `This theme's body text is below WCAG AA: ${list}. Import it anyway as a personal theme? Your acceptance is recorded.`
          )
        ) {
          try {
            const t = await importThemeFile(text, true)
            toast.success(`Imported ${t.name} with low contrast accepted.`)
            await open(t.id)
          } catch (e2) {
            toast.error((e2 as Error).message)
          }
        }
        return
      }
      toast.error(`Couldn't import: ${(e as Error).message}`)
    }
  }

  async function buildFrom(id: string) {
    try {
      const t = await duplicateTheme(id)
      toast.success(`Made ${t.name}. Edit away.`)
      await open(t.id)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return { importFile, buildFrom, maxBytes }
}
