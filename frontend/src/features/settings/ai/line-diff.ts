export type DiffLine = { kind: "same" | "add" | "del"; text: string }

/** Line diff (longest common subsequence) between two prompt versions. */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n")
  const b = after.split("\n")
  const m = a.length
  const n = b.length
  const lcs: number[][] = Array.from({ length: m + 1 }, () =>
    new Array<number>(n + 1).fill(0)
  )
  for (let i = m - 1; i >= 0; i--)
    for (let j = n - 1; j >= 0; j--)
      lcs[i][j] =
        a[i] === b[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1])
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ kind: "del", text: a[i++] })
    } else {
      out.push({ kind: "add", text: b[j++] })
    }
  }
  while (i < m) out.push({ kind: "del", text: a[i++] })
  while (j < n) out.push({ kind: "add", text: b[j++] })
  return out
}
