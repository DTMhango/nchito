const BOARD_LABEL: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workable: "Workable",
  workday: "Workday",
}

export const boardLabel = (type: string) =>
  BOARD_LABEL[type] ?? type.charAt(0).toUpperCase() + type.slice(1)
