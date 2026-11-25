import type { MetadataRoute } from "next";

// На бесплатном Render сервис засыпает через 15 минут без входящего трафика.
// Поисковые краулеры не должны ни будить инстанс, ни расходовать трафик тарифа.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", disallow: "/" }],
  };
}
