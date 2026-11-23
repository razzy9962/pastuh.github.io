import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { eq } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import { db } from "@/db";
import { workspaces } from "@/db/schema";
import { DEFAULT_SETTINGS, INSTRUMENTS, TIMEFRAMES, parseFormula, type WorkspaceSettings } from "@/lib/market";

export const dynamic = "force-dynamic";
async function workspace() {
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
  if (!Array.isArray(s.watchlist) || s.watchlist.length > 30 || !s.watchlist.every(symbol => INSTRUMENTS.some(i => i.symbol === symbol))) return false;
  if (!Array.isArray(s.indicators) || s.indicators.length > 20 || !s.indicators.every(i => typeof i.id === "string" && i.id.length < 80 && typeof i.name === "string" && i.name.length > 0 && i.name.length <= 60 && ["sma", "ema", "bb", "rsi"].includes(i.type) && Number.isInteger(i.period) && i.period >= 2 && i.period <= 200 && /^#[0-9a-f]{6}$/i.test(i.color) && typeof i.enabled === "boolean" && (!i.custom || (typeof i.formula === "string" && !!parseFormula(i.formula))))) return false;
  if (!s.drawings || typeof s.drawings !== "object" || Array.isArray(s.drawings) || Object.keys(s.drawings).length > 30) return false;
  return Object.entries(s.drawings).every(([symbol, drawings]) => INSTRUMENTS.some(i => i.symbol === symbol) && Array.isArray(drawings) && drawings.length <= 40 && drawings.every(d => typeof d.id === "string" && d.id.length < 80 && ["horizontal", "trend"].includes(d.type) && Number.isFinite(d.price) && d.price > 0 && Number.isFinite(d.time) && /^#[0-9a-f]{6}$/i.test(d.color) && (d.type !== "trend" || (Number.isFinite(d.endTime) && Number.isFinite(d.endPrice) && d.endPrice! > 0))));
}

export async function GET() {
  try { const row = await workspace(); return NextResponse.json({ settings: row.settings, updatedAt: row.updatedAt }); }
  catch { return NextResponse.json({ error: "Не удалось загрузить рабочее пространство" }, { status: 503 }); }
}
export async function PATCH(request: NextRequest) {
  try {
    const text = await request.text();
    if (text.length > 60000) return NextResponse.json({ error: "Слишком много данных" }, { status: 413 });
    let settings: unknown;
    try { settings = JSON.parse(text); } catch { return NextResponse.json({ error: "Некорректный JSON" }, { status: 400 }); }
    if (!valid(settings)) return NextResponse.json({ error: "Некорректные настройки рабочего пространства" }, { status: 400 });
    const row = await workspace();
    const now = new Date();
    await db.update(workspaces).set({ settings, updatedAt: now }).where(eq(workspaces.id, row.id));
    return NextResponse.json({ saved: true, updatedAt: now.toISOString() });
  } catch { return NextResponse.json({ error: "Не удалось сохранить настройки" }, { status: 503 }); }
}
