/** People attached to roles (Job page, People tab). Invented; example.com addresses only. */
import type { ContactOut } from "@/features/jobs/api"
import { appliedJobId } from "./jobs"

export const seedContacts = (): ContactOut[] => [
  {
    id: "c1",
    created_at: "2026-11-21T09:00:00.000Z",
    updated_at: "2026-11-21T09:00:00.000Z",
    // Zambezi Mining Systems, Data Platform Lead (the application waiting for approval).
    job_id: appliedJobId(5),
    name: "Mwila Banda",
    role: "Recruiter",
    email: "mwila.banda@example.com",
    link: null,
    notes: "Prefers email before noon.",
    origin: "owner",
  },
]
