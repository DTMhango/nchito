import { setupServer } from "msw/node"
import { handlers } from "@/mocks/handlers"

/** The same handlers the dev mock uses, for tests. Override per test with server.use(...). */
export const server = setupServer(...handlers)
