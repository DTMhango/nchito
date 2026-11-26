import { useCallback, useEffect, useMemo, useState } from "react"
import { Link, useBlocker, useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft,
  Check,
  Copy,
  Download,
  History,
  Lock,
  Moon,
  Redo2,
  Save,
  Star,
  Sun,
  Trash2,
  Undo2,
  Wand2,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/chip"
import { Segmented } from "@/components/segmented"
import { View } from "@/components/view"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { isApiError } from "@/lib/api/client"
import { useTheme } from "@/themes/provider"
import { themeSchema, type Mode, type Theme } from "@/themes/schema"
import { DEFICIENCIES, type Deficiency } from "@/themes/cvd"
import { TOKEN_SPEC, tokensInGroup } from "@/themes/spec"
import { themeIssues } from "@/themes/validate"
import {
  deleteStudioTheme,
  downloadJson,
  duplicateTheme,
  exportTheme,
  fileSlug,
  invalidateThemes,
  redoTheme,
  saveTheme,
  setDefaultTheme,
  settingValueQuery,
  studioKeys,
  studioThemesQuery,
  toBody,
  undoTheme,
  type ThemeBody,
  type ThemeOut,
} from "./api"
import { BasicsSection, ChartSection, GenerateSection } from "./sections"
import { ContrastPanel, contrastResults } from "./contrast-panel"
import { RevisionList } from "./revision-list"
import { StudioPreview } from "./preview"
import { TokenField } from "./token-field"

const GROUPS = TOKEN_SPEC.groups.filter((g) => g.key !== "chart")

/** Theme studio (DESIGN 10.4): edit a theme with a live, scoped preview and a contrast check. */
export function ThemeStudioPage({ themeId }: { themeId: string }) {
  const q = useQuery(studioThemesQuery())
  const theme = q.data?.find((t) => t.id === themeId)
  if (q.isLoading)
    return (
      <View>
        <p className="text-muted-foreground">Loading the theme...</p>
      </View>
    )
  if (!theme)
    return (
      <View>
        <p className="mb-3">That theme doesn't exist any more.</p>
        <Button asChild variant="outline">
          <Link to="/settings/appearance">Back to Appearance</Link>
        </Button>
      </View>
    )
  return <Studio key={`${theme.id}:${theme.revision ?? "b"}`} theme={theme} />
}

function Studio({ theme }: { theme: ThemeOut }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const app = useTheme()
  const readOnly = theme.builtin
  const saved = useMemo(() => toBody(theme), [theme])
  const [draft, setDraft] = useState<ThemeBody>(saved)
  const [editMode, setEditMode] = useState<Mode>(app.mode)
  const [deficiency, setDeficiency] = useState<Deficiency | "none">("none")
  const [accept, setAccept] = useState(false)
  const [tab, setTab] = useState("basics")
  const [showHistory, setShowHistory] = useState(false)
  const minDistance = useQuery(settingValueQuery("themes.status_min_distance"))

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const issues = useMemo(
    () =>
      themeIssues({
        ...draft,
        fonts: { ...draft.fonts },
        score: { ...draft.score },
      }),
    [draft]
  )
  const issueAt = (path: string) => issues.find((i) => i.path === path)?.message
  const results = useMemo(() => contrastResults(draft), [draft])
  const blocking = results.filter((r) => r.blocking)
  const blocked = blocking.length > 0 && !accept
  const canSave = !readOnly && dirty && issues.length === 0 && !blocked

  // The draft as a renderable theme (for the scoped preview only; the app root is untouched).
  const previewTheme: Theme = useMemo(() => {
    const parsed = themeSchema.safeParse({
      ...draft,
      id: theme.id,
      builtin: theme.builtin,
      description: draft.description ?? undefined,
    })
    return parsed.success
      ? parsed.data
      : themeSchema.parse({
          ...saved,
          id: theme.id,
          builtin: theme.builtin,
          description: saved.description ?? undefined,
        })
  }, [draft, saved, theme.id, theme.builtin])

  const setToken = useCallback(
    (mode: Mode, name: string, value: string | undefined) => {
      setDraft((d) => {
        const map = { ...d[mode] }
        if (value === undefined) delete map[name]
        else map[name] = value
        return { ...d, [mode]: map }
      })
    },
    []
  )

  const afterChange = (t: ThemeOut, message?: string) => {
    qc.setQueryData<ThemeOut[]>(studioKeys.themes, (list) =>
      list?.map((x) => (x.id === t.id ? t : x))
    )
    invalidateThemes(qc, t.id)
    if (message) toast.success(message)
  }

  const save = useMutation({
    mutationFn: () => saveTheme(theme.id, draft, accept),
    onSuccess: (t) => afterChange(t, "Theme saved."),
    onError: (e) => toast.error(e.message),
  })
  const undo = useMutation({
    mutationFn: () => undoTheme(theme.id),
    onSuccess: (t) => afterChange(t),
    onError: (e) => toast.error(e.message),
  })
  const redo = useMutation({
    mutationFn: () => redoTheme(theme.id),
    onSuccess: (t) => afterChange(t),
    onError: (e) => toast.error(e.message),
  })
  const makeDefault = useMutation({
    mutationFn: () => setDefaultTheme(theme.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: studioKeys.themes })
      invalidateThemes(qc)
      toast.success(`${theme.name} is now the default theme.`)
    },
    onError: (e) => toast.error(e.message),
  })
  const duplicate = useMutation({
    mutationFn: () => duplicateTheme(theme.id),
    onSuccess: async (t) => {
      await qc.invalidateQueries({ queryKey: studioKeys.themes })
      invalidateThemes(qc)
      toast.success(`Made ${t.name}. Edit away.`)
      void navigate({ to: "/theme-studio/$themeId", params: { themeId: t.id } })
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => deleteStudioTheme(theme.id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: studioKeys.themes })
      invalidateThemes(qc)
      toast.success(`${theme.name} deleted.`)
      void navigate({ to: "/settings/appearance" })
    },
    onError: (e) =>
      toast.error(
        isApiError(e, 409) ? e.message : `Couldn't delete: ${e.message}`
      ),
  })

  const active = app.theme.id === theme.id
  const deleteReason = theme.builtin
    ? "Built-in themes can't be deleted."
    : active
      ? "This theme is in use. Switch to another first."
      : theme.is_default
        ? "This is the default theme. Make another the default first."
        : null

  const doUndo = useCallback(() => {
    if (dirty) setDraft(saved)
    else if (theme.can_undo) undo.mutate()
  }, [dirty, saved, theme.can_undo, undo])

  // Keyboard: Ctrl/Cmd+S saves; Ctrl/Cmd+Z / Shift+Ctrl/Cmd+Z undo and redo outside text fields.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      const k = e.key.toLowerCase()
      if (k === "s") {
        e.preventDefault()
        if (canSave) save.mutate()
        return
      }
      const el = e.target as HTMLElement | null
      if (
        el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.tagName === "SELECT")
      )
        return
      if (k === "z" && !e.shiftKey && !readOnly) {
        e.preventDefault()
        doUndo()
      } else if ((k === "z" && e.shiftKey) || k === "y") {
        e.preventDefault()
        if (!dirty && theme.can_redo) redo.mutate()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [canSave, save, doUndo, redo, dirty, theme.can_redo, readOnly])

  useBlocker({
    shouldBlockFn: () =>
      dirty &&
      !window.confirm("Leave the studio? Your unsaved changes will be lost."),
    enableBeforeUnload: () => dirty,
  })

  const exportFile = async () => {
    try {
      downloadJson(
        `${fileSlug(theme.name)}.theme.json`,
        await exportTheme(theme.id)
      )
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <View className="max-w-none">
      <header className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button
          asChild
          variant="ghost"
          size="icon-sm"
          aria-label="Back to Appearance"
        >
          <Link to="/settings/appearance">
            <ArrowLeft aria-hidden="true" />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <div className="eyebrow">Theme studio</div>
          <h2 className="flex flex-wrap items-center gap-2 text-2xl">
            <span className="truncate">{draft.name || theme.name}</span>
            {theme.builtin && (
              <Chip tone="line">
                <Lock aria-hidden="true" />
                Built-in
              </Chip>
            )}
            {active && <Chip tone="primary">In use</Chip>}
            {theme.is_default && <Chip tone="info">Default</Chip>}
            {dirty && <Chip tone="warn">Unsaved</Chip>}
            {theme.revision != null && !dirty && (
              <span className="text-[0.8rem] font-normal text-faint">
                revision {theme.revision}
              </span>
            )}
          </h2>
        </div>
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="toolbar"
          aria-label="Theme actions"
        >
          {readOnly ? (
            <Button
              onClick={() => duplicate.mutate()}
              disabled={duplicate.isPending}
            >
              <Copy aria-hidden="true" /> Duplicate to edit
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={dirty ? "Discard unsaved changes" : "Undo"}
                title="Undo (Ctrl+Z)"
                disabled={!dirty && !theme.can_undo}
                onClick={doUndo}
              >
                <Undo2 aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Redo"
                title="Redo (Ctrl+Shift+Z)"
                disabled={dirty || !theme.can_redo}
                onClick={() => redo.mutate()}
              >
                <Redo2 aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-pressed={showHistory}
                onClick={() => setShowHistory((v) => !v)}
              >
                <History aria-hidden="true" /> History
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => duplicate.mutate()}
              >
                <Copy aria-hidden="true" /> Duplicate
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" onClick={exportFile}>
            <Download aria-hidden="true" /> Export
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={theme.is_default || dirty}
            onClick={() => makeDefault.mutate()}
            title={dirty ? "Save first" : undefined}
          >
            <Star aria-hidden="true" /> Make default
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={active || dirty}
            title={dirty ? "Save first" : undefined}
            onClick={() => {
              app.setAppearance({ theme_id: theme.id })
              toast.success(`${theme.name} theme on.`)
            }}
          >
            <Check aria-hidden="true" /> Use this theme
          </Button>
          {!readOnly && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Delete theme"
              title={deleteReason ?? "Delete theme"}
              disabled={!!deleteReason}
              onClick={() => {
                if (
                  window.confirm(`Delete ${theme.name}? This can't be undone.`)
                )
                  remove.mutate()
              }}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          )}
          {!readOnly && (
            <Button
              onClick={() => save.mutate()}
              disabled={!canSave || save.isPending}
              title="Save (Ctrl+S)"
            >
              <Save aria-hidden="true" /> Save
            </Button>
          )}
        </div>
      </header>

      {readOnly && (
        <p className="mb-4 flex items-center gap-2 rounded-md border border-border bg-sunken px-3 py-2 text-[0.88rem] text-muted-foreground">
          <Lock className="size-4" aria-hidden="true" /> Built-in themes are
          read-only. Duplicate this one to make your own version; you can look
          around and preview freely.
        </p>
      )}

      {blocking.length > 0 && !readOnly && (
        <div
          role="alert"
          className="mb-4 grid gap-2 rounded-md border border-danger bg-danger-soft px-3 py-2.5 text-[0.88rem]"
        >
          <b className="font-semibold text-danger">
            Body text is below WCAG AA in {blocking.length}{" "}
            {blocking.length === 1 ? "place" : "places"}, so the theme can't be
            saved.
          </b>
          <span className="text-foreground">
            Use a suggested colour in the contrast list, or keep it for this
            personal theme. Accepting is recorded on the theme and in the
            activity log.
          </span>
          <label className="flex items-center gap-2 font-medium text-foreground">
            <Checkbox
              checked={accept}
              onCheckedChange={(v) => setAccept(v === true)}
            />
            I accept low contrast for this personal theme
          </label>
        </div>
      )}
      {theme.contrast_waiver && (
        <p className="mb-4 text-[0.82rem] text-warn">
          Low contrast accepted on{" "}
          {new Date(theme.contrast_waiver.accepted_at).toLocaleDateString()} for{" "}
          {theme.contrast_waiver.pairs
            .map((p) => `${p.fg} on ${p.bg} (${p.mode}, ${p.ratio})`)
            .join(", ")}
          .
        </p>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(380px,460px)_minmax(0,1fr)]">
        <section aria-label="Editor" className="grid min-w-0 gap-3">
          <div className="flex items-center justify-between gap-2">
            <Segmented<Mode>
              aria-label="Editing mode"
              value={editMode}
              onValueChange={setEditMode}
              options={[
                { value: "light", label: "Light", icon: Sun },
                { value: "dark", label: "Dark", icon: Moon },
              ]}
            />
            <span className="text-[0.8rem] text-faint">
              Edits apply to the {editMode} variant
            </span>
          </div>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList
              className="flex h-auto w-full flex-wrap justify-start"
              aria-label="Token groups"
            >
              <TabsTrigger value="basics">Basics</TabsTrigger>
              <TabsTrigger value="generate">
                <Wand2 aria-hidden="true" />
                Generate
              </TabsTrigger>
              {GROUPS.map((g) => (
                <TabsTrigger key={g.key} value={g.key}>
                  {g.label}
                </TabsTrigger>
              ))}
              <TabsTrigger value="chart">Chart</TabsTrigger>
            </TabsList>
            <div className="mt-2 rounded-lg border border-border bg-surface p-3">
              <TabsContent value="basics">
                <BasicsSection
                  draft={draft}
                  setDraft={setDraft}
                  readOnly={readOnly}
                  issueAt={issueAt}
                />
              </TabsContent>
              <TabsContent value="generate">
                <GenerateSection
                  draft={draft}
                  setDraft={setDraft}
                  readOnly={readOnly}
                />
              </TabsContent>
              {GROUPS.map((g) => (
                <TabsContent key={g.key} value={g.key}>
                  <div className="divide-y divide-border">
                    {tokensInGroup(g.key).map((name) => (
                      <TokenField
                        key={`${editMode}-${name}`}
                        name={name}
                        spec={TOKEN_SPEC.tokens[name]}
                        value={draft[editMode][name]}
                        disabled={readOnly}
                        issue={issueAt(`${editMode}.${name}`)}
                        onChange={(v) => setToken(editMode, name, v)}
                      />
                    ))}
                  </div>
                </TabsContent>
              ))}
              <TabsContent value="chart">
                <ChartSection
                  draft={draft}
                  setDraft={setDraft}
                  mode={editMode}
                  setToken={setToken}
                  readOnly={readOnly}
                  issueAt={issueAt}
                />
              </TabsContent>
            </div>
          </Tabs>
          {showHistory && !readOnly && (
            <RevisionList
              theme={theme}
              dirty={dirty}
              onRestored={(t) =>
                afterChange(t, `Back to revision ${t.revision}.`)
              }
            />
          )}
        </section>

        <section
          aria-label="Preview and checks"
          className="grid min-w-0 gap-4 xl:sticky xl:top-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[0.86rem] font-semibold">Preview</span>
            <Segmented<Mode>
              aria-label="Preview mode"
              value={editMode}
              onValueChange={setEditMode}
              options={[
                { value: "light", label: "Light", icon: Sun },
                { value: "dark", label: "Dark", icon: Moon },
              ]}
            />
            <label className="ml-auto flex items-center gap-2 text-[0.84rem] text-muted-foreground">
              Colour vision
              <select
                aria-label="Colour vision simulation"
                value={deficiency}
                onChange={(e) =>
                  setDeficiency(e.target.value as Deficiency | "none")
                }
                className="h-8 rounded-md border field-focus border-border bg-surface px-2 text-foreground"
              >
                <option value="none">Normal</option>
                {DEFICIENCIES.map((d) => (
                  <option key={d} value={d}>
                    {d[0].toUpperCase() + d.slice(1)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <StudioPreview
            theme={previewTheme}
            mode={editMode}
            deficiency={deficiency === "none" ? null : deficiency}
          />
          <ContrastPanel
            draft={draft}
            results={results}
            readOnly={readOnly}
            minStatusDistance={
              typeof minDistance.data === "number" ? minDistance.data : null
            }
            onFix={(mode, token, value) => setToken(mode, token, value)}
          />
          {issues.length > 0 && !readOnly && (
            <div
              role="status"
              className="rounded-md border border-warn bg-warn-soft px-3 py-2 text-[0.84rem]"
            >
              <b className="font-semibold">Fix before saving:</b>{" "}
              {issues
                .slice(0, 4)
                .map((i) => `${i.path} (${i.message})`)
                .join("; ")}
              {issues.length > 4 ? ` and ${issues.length - 4} more` : ""}
            </div>
          )}
        </section>
      </div>
    </View>
  )
}
