import { pool } from "@/db";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Проверка живости для Render (health check) и статуса хранилища.
export async function GET() {
  const memory = process.memoryUsage();
  const payload = {
    ok: true,
    database: pool ? "configured" : "disabled",
    uptime: Math.round(process.uptime()),
    memoryMb: { rss: Math.round(memory.rss / 1048576), heap: Math.round(memory.heapUsed / 1048576) },
  };
  // Health check Render не должен ронять сервис из-за недоступной базы:
  // приложение полностью работает и без PostgreSQL (настройки в localStorage),
  // поэтому статус всегда 200, а состояние базы отдаётся полем database.
  if (!pool) return Response.json(payload, { headers: { "Cache-Control": "no-store" } });
  const started = Date.now();
  try {
    await pool.query({ text: "select 1", query_timeout: 2000 } as never);
    return Response.json({ ...payload, database: "ready", latencyMs: Date.now() - started }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ ...payload, database: "unreachable" }, { headers: { "Cache-Control": "no-store" } });
  }
}
