import Terminal from "@/components/terminal";
import { INSTRUMENTS, demoQuote, generateCandles } from "@/lib/market";

export const dynamic = "force-dynamic";
export default function HomePage() {
  return <Terminal initialCandles={generateCandles("SBER", "1d")} initialQuotes={INSTRUMENTS.map(demoQuote)} />;
}
