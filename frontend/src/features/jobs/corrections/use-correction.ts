import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

/** Run a correction, refresh everything about the role, and say what happened in a toast. */
export function useCorrection<V>(
  run: (v: V) => Promise<unknown>,
  done: string,
  onDone: () => void
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      void qc.invalidateQueries({ queryKey: ["applications"] })
      toast.success(done)
      onDone()
    },
  })
}

export const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong. Try again."
