import { NextRequest, NextResponse } from "next/server";
import { getCandles, getQuotes } from "@/lib/market-server";
import { INSTRUMENTS, TIMEFRAMES, type Timeframe } from "@/lib/market";

export const dynamic = "force-dynamic";
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  if (params.get("mode") === "quotes") return NextResponse.json({ quotes: await getQuotes(), asOf: new Date().toISOString() });
  const symbol = params.get("symbol") ?? "SBER";
  const timeframe = params.get("timeframe") ?? "1d";
  if (!INSTRUMENTS.some(i => i.symbol === symbol) || !TIMEFRAMES.some(t => t.value === timeframe)) return NextResponse.json({ error: "Неизвестный инструмент или интервал" }, { status: 400 });
  return NextResponse.json(await getCandles(symbol, timeframe as Timeframe));
}
