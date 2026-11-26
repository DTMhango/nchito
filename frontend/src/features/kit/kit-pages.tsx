import { Outlet } from "@tanstack/react-router"
import { CountBadge } from "@/components/chip"
import { SubNav, SubNavLink } from "@/components/sub-nav"
import { View } from "@/components/view"
import { KIT_SECTIONS } from "@/app/shell/nav"
import { useReviewCounts } from "./common"
import { AnswersPage } from "./answers-page"
import { DocumentsPage } from "./documents-page"
import { GuardrailsPage } from "./guardrails-page"
import { LibraryPage } from "./library-page"
import { TemplatesPage } from "./templates-page"
import { TracksPage } from "./tracks-page"

/** Kit: everything the app may say about you (DESIGN 5). Sub-nav over six sections. */
export function KitLayout() {
  const counts = useReviewCounts()
  return (
    <View>
      <SubNav label="Kit sections" className="mb-5">
        {KIT_SECTIONS.map((s) => {
          const n = counts[s.to.split("/").pop() ?? ""] ?? 0
          return (
            <SubNavLink key={s.to} to={s.to}>
              {s.label}
              {n > 0 && (
                <CountBadge aria-label={`${n} to review`} title="Needs review">
                  {n}
                </CountBadge>
              )}
            </SubNavLink>
          )
        })}
      </SubNav>
      <Outlet />
    </View>
  )
}

const PAGES = {
  library: LibraryPage,
  tracks: TracksPage,
  guardrails: GuardrailsPage,
  answers: AnswersPage,
  documents: DocumentsPage,
  templates: TemplatesPage,
}

export function KitSection({ section }: { section: keyof typeof PAGES }) {
  const Page = PAGES[section]
  return <Page />
}
