import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/inter";
import "./globals.css";

export const viewport: Viewport = { themeColor: "#131722", colorScheme: "dark" };

export const metadata: Metadata = {
  title: "MOEX Terminal — ваш взгляд на рынок",
  description: "Аналитический терминал Московской биржи: интерактивные графики, котировки, технические и пользовательские индикаторы. Подключение к Т-Инвест только для чтения.",
  robots: { index: false, follow: false },
  applicationName: "MOEX Terminal",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "MOEX Terminal", statusBarStyle: "black-translucent" },
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="ru"><body>{children}</body></html>;
}
