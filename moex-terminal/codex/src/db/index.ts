import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

// PostgreSQL опционален: без DATABASE_URL терминал работает на локальной копии
// настроек в браузере, а /api/health честно сообщает об отсутствии базы.
const databaseUrl = process.env.DATABASE_URL;

const globalForDb = globalThis as typeof globalThis & {
  __arenaNextJsPostgresqlPool?: Pool;
};

export const pool: Pool | null = databaseUrl
  ? globalForDb.__arenaNextJsPostgresqlPool ?? new Pool({ connectionString: databaseUrl })
  : null;

if (pool && process.env.NODE_ENV !== "production") {
  globalForDb.__arenaNextJsPostgresqlPool = pool;
}

export function requireDb() {
  if (!pool) throw new Error("DATABASE_URL is required");
  return drizzle(pool);
}
