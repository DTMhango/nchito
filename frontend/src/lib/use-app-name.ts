import { useQuery } from "@tanstack/react-query"
import { meQuery } from "@/lib/api/endpoints"

/** Product name is a setting (APP_NAME, overridable in the UI). Falls back to Nchito. */
export const DEFAULT_APP_NAME = "Nchito"

export function useAppName(): string {
  const me = useQuery(meQuery())
  return me.data?.app_name || DEFAULT_APP_NAME
}
