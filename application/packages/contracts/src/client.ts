import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";

// All generated paths already include /api. The browser supplies its own origin.
// No retry middleware: consequential command recovery belongs to its later slice.
export const api = createClient<paths>({ credentials: "same-origin" });
