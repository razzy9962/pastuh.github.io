import { NextRequest, NextResponse } from "next/server";
import { eq } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { pool, requireDb } from "@/db";
import { workspaces } from "@/db/schema";
import { DEFAULT_SETTINGS, INSTRUMENTS, TIMEFRAMES, sanitizeSmcSettings, type WorkspaceSettings } from "@/lib/market";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Без PostgreSQL (например, на бесплатном инстансе Render) рабочее пространство
// живёт в браузере: API честно отвечает 503, клиент переключается на localStorage.
const NO_DB = () => NextResponse.json({ error: "Сохранение на сервере не настроено", storage: "local" }, { status: 503, headers: { "Cache-Control": "no-store" } });

async function workspace() {
  const db = requireDb();
  const jar = await cookies();
  let id = jar.get("moex_workspace")?.value;
  if (!id || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
    id = randomUUID();
    jar.set("moex_workspace", id, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 31536000 });
  }
  const [row] = await db.select().from(workspaces).where(eq(workspaces.id, id)).limit(1);
  if (row) return row;
  const [created] = await db.insert(workspaces).values({ id, settings: DEFAULT_SETTINGS }).onConflictDoNothing().returning();
  if (created) return created;
  const [existing] = await db.select().from(workspaces).where(eq(workspaces.id, id)).limit(1);
  return existing;
}

function valid(value: unknown): value is WorkspaceSettings {
  if (!value || typeof value !== "object") return false;
  const s = value as WorkspaceSettings;
  if (!INSTRUMENTS.some(i => i.symbol === s.symbol) || !TIMEFRAMES.some(t => t.value === s.timeframe)) return false;
  if (!["candles", "line", "area"].includes(s.chartType) || typeof s.showVolume !== "boolean") return false;
  if (!Array.isArray(s.watchlist) || s.watchlist.length > 200 || !s.watchlist.every(symbol => INSTRUMENTS.some(i => i.symbol === symbol))) return false;
  if (!s.drawings || typeof s.drawings !== "object" || Array.isArray(s.drawings) || Object.keys(s.drawings).length > 200) return false;
  return Object.entries(s.drawings).every(([symbol, drawings]) => INSTRUMENTS.some(i => i.symbol === symbol) && Array.isArray(drawings) && drawings.length <= 40 && drawings.every(d => typeof d.id === "string" && d.id.length < 80 && ["horizontal", "trend"].includes(d.type) && Number.isFinite(d.price) && d.price > 0 && Number.isFinite(d.time) && /^#[0-9a-f]{6}$/i.test(d.color) && (d.type !== "trend" || (Number.isFinite(d.endTime) && Number.isFinite(d.endPrice!) && d.endPrice! > 0))));
}

export async function GET() {
  if (!pool) return NO_DB();
  try { const row = await workspace(); return NextResponse.json({ settings: { ...row.settings, smc: sanitizeSmcSettings(row.settings?.smc) }, updatedAt: row.updatedAt }); }
  catch { return NextResponse.json({ error: "Не удалось загрузить рабочее пространство", storage: "local" }, { status: 503 }); }
}

export async function PATCH(request: NextRequest) {
  if (!pool) return NO_DB();
  try {
    const text = await request.text();
    if (text.length > 60000) return NextResponse.json({ error: "Слишком много данных" }, { status: 413 });
    let settings: unknown;
    try { settings = JSON.parse(text); } catch { return NextResponse.json({ error: "Некорректный JSON" }, { status: 400 }); }
    if (!valid(settings)) return NextResponse.json({ error: "Некорректные настройки рабочего пространства" }, { status: 400 });
    const db = requireDb();
    const clean: WorkspaceSettings = { ...(settings as WorkspaceSettings), smc: sanitizeSmcSettings((settings as WorkspaceSettings).smc) };
    const row = await workspace();
    const now = new Date();
    await db.update(workspaces).set({ settings: clean, updatedAt: now }).where(eq(workspaces.id, row.id));
    return NextResponse.json({ saved: true, updatedAt: now.toISOString() });
  } catch { return NextResponse.json({ error: "Не удалось сохранить настройки", storage: "local" }, { status: 503 }); }
}
