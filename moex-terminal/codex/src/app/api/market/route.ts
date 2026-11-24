import { NextRequest, NextResponse } from "next/server";
import { getCandles, getQuotes } from "@/lib/market-server";
import { INSTRUMENTS, TIMEFRAMES, type Timeframe } from "@/lib/market";
import { jsonWithCache } from "@/lib/http";

export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  // Котировки обновляются раз в 25 секунд на сервере, поэтому 15 секунд кеша в браузере безопасны.
  if (params.get("mode") === "quotes") return jsonWithCache(request, { quotes: await getQuotes(), asOf: new Date().toISOString() }, 15);
  // Каталог меняется только вместе с деплоем — кешируем надолго.
  if (params.get("mode") === "symbols") return jsonWithCache(request, { symbols: INSTRUMENTS.map(i => ({ symbol: i.symbol, name: i.name, kind: i.kind, tier: i.tier ?? null, lot: i.lot })) }, 3600);
  const symbol = params.get("symbol") ?? "SBER";
  const timeframe = params.get("timeframe") ?? "1d";
  if (!INSTRUMENTS.some(i => i.symbol === symbol) || !TIMEFRAMES.some(t => t.value === timeframe)) return NextResponse.json({ error: "Неизвестный инструмент или интервал" }, { status: 400 });
  return jsonWithCache(request, await getCandles(symbol, timeframe as Timeframe), 15);
}
