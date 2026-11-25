import { redirect, type ParsedLocation } from "@tanstack/react-router"
import type { QueryClient } from "@tanstack/react-query"
import { meQuery, setupStatusQuery } from "@/lib/api/endpoints"

export type RouterContext = { queryClient: QueryClient }

/**
 * Route guard for everything behind sign-in.
 * - No owner yet: first-run setup.
 * - Owner but no session: sign-in, returning here afterwards.
 */
export async function requireSession({
  context,
  location,
}: {
  context: RouterContext
  location: ParsedLocation
}) {
  const status = await context.queryClient.ensureQueryData(setupStatusQuery())
  if (!status.owner_exists) throw redirect({ to: "/setup" })
  const me = await context.queryClient.ensureQueryData(meQuery())
  if (!me)
    throw redirect({ to: "/sign-in", search: { redirect: location.href } })
  return { me }
}

/** Setup is only reachable while there is no owner. */
export async function requireNoOwner({ context }: { context: RouterContext }) {
  const status = await context.queryClient.ensureQueryData(setupStatusQuery())
  if (status.owner_exists) throw redirect({ to: "/sign-in" })
}

/** Sign-in redirects away when already signed in, and to setup when there is no owner. */
export async function requireSignedOut({
  context,
  search,
}: {
  context: RouterContext
  search: { redirect?: string }
}) {
  const status = await context.queryClient.ensureQueryData(setupStatusQuery())
  if (!status.owner_exists) throw redirect({ to: "/setup" })
  const me = await context.queryClient.ensureQueryData(meQuery())
  if (me) throw redirect({ href: safeRedirect(search.redirect) })
}

/** Only follow same-app paths after sign-in; anything else goes to Today. */
export function safeRedirect(target: string | undefined): string {
  if (!target || !target.startsWith("/") || target.startsWith("//"))
    return "/today"
  if (target.startsWith("/sign-in") || target.startsWith("/setup"))
    return "/today"
  return target
}
