import { jsonb, pgTable, timestamp, uuid } from "drizzle-orm/pg-core";
import type { WorkspaceSettings } from "@/lib/market";

export const workspaces = pgTable("moex_workspaces", {
  id: uuid("id").primaryKey().defaultRandom(),
  settings: jsonb("settings").$type<WorkspaceSettings>().notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow().notNull(),
});
