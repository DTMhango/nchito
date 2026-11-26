/** The Job page's tabs, in order (the route validates `?tab=` against these). */
export const JOB_TABS = [
  "overview",
  "posting",
  "fit",
  "documents",
  "application",
  "messages",
  "people",
  "interview",
  "schedule",
  "changes",
  "activity",
] as const
export type JobTab = (typeof JOB_TABS)[number]
