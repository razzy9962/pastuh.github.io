import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/inter";
import "./globals.css";

export const metadata: Metadata = {
  title: "MOEX Terminal — ваш взгляд на рынок",
  description: "Аналитический терминал Московской биржи: интерактивные графики, котировки, технические и пользовательские индикаторы. Подключение к Т-Инвест только для чтения.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="ru"><body>{children}</body></html>;
}
