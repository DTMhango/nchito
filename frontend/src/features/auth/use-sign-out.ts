import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { toast } from "sonner"
import { keys, logout } from "@/lib/api/endpoints"

/** Sign out, drop cached private data, and go to the sign-in screen. */
export function useSignOut() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  return async () => {
    try {
      await logout()
    } catch {
      /* the session may already be gone; carry on */
    }
    qc.setQueryData(keys.me, null)
    qc.removeQueries({
      predicate: (q) => q.queryKey[0] !== "auth" && q.queryKey[0] !== "setup",
    })
    toast("Signed out.")
    await navigate({ to: "/sign-in" })
  }
}
