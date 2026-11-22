import { Dashboard } from "../../../../components/dashboard";
export default async function ProductionPage({ params }: PageProps<"/canais/[canal]/producao">) {
  const { canal } = await params;
  return <Dashboard channelBase={"/canais/" + encodeURIComponent(canal)} />;
}
