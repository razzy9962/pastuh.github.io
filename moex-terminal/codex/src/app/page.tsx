import Terminal from "@/components/terminal";

// Данные приходят только из API (Т-Инвест / MOEX): выдуманных баров и цен больше нет,
// поэтому страница может рендериться статически, а график появляется после ответа API.
export default function HomePage() {
  return <Terminal />;
}
