import { InsightsVideo } from "../../../../../components/insights-video";
import { consultaPagina } from "../../../../../lib/insights";
export default async function VideoPage({ params, searchParams }: PageProps<"/canais/[canal]/videos/[videoId]">) {
  const { canal, videoId } = await params;
  return <InsightsVideo canal={canal} videoId={videoId} consulta={consultaPagina(await searchParams)} />;
}
