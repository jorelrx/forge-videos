import { SessaoStudio } from "../../../components/sessao-studio";
export default async function ChannelLayout({ children, params }: LayoutProps<"/canais/[canal]">) {
  const { canal } = await params;
  return <SessaoStudio canalId={canal}>{children}</SessaoStudio>;
}
