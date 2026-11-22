import { InsightsCanal } from "../../../components/insights-canal";
import { consultaPagina } from "../../../lib/insights";
export default async function ChannelPage({ params, searchParams }: PageProps<"/canais/[canal]">) {
  return <InsightsCanal canal={(await params).canal} consulta={consultaPagina(await searchParams)} />;
}
