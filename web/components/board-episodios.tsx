import Link from "next/link";
import type { EpisodioBoard, JanelaEpisodio } from "../lib/board-criativo";
import { dataCivil, dataPublicacao, numero } from "../lib/insights";

const momentos: Record<EpisodioBoard["momento"], string> = {
  em_producao: "Em produção",
  cancelado: "Encaminhamento cancelado",
  enviado: "Enviado ao YouTube, ainda não público",
  agendado: "Agendado no YouTube",
  publico: "Público",
  janela_completa: "Público, com janela de medição completa",
};

function Janela({nome, janela}: {nome: string; janela: JanelaEpisodio}) {
  const views = janela.observacoes.find(o => o.medida === "views" && o.valor != null);
  if (!janela.completa) return <li>{nome} pendente até {dataCivil(janela.fim)}</li>;
  return <li>{nome} completa{views ? ` · ${numero(views.valor)} ${views.unidade}` : " · medida ainda não lida"}</li>;
}

export function EpisodiosBoard({canal, episodios}: {canal: string; episodios: EpisodioBoard[]}) {
  if (!episodios.length) return null;
  const base = "/canais/" + encodeURIComponent(canal);
  return <section className="panel board-episodes" aria-labelledby="board-episodes-title">
    <h2 id="board-episodes-title">Episódios do Board</h2>
    <ul>
      {episodios.map(item => <li key={item.aprovacao_id}>
        <div><strong>{item.titulo}</strong> <small>revisão {item.revisao}</small></div>
        <p>{momentos[item.momento]}
          {item.momento === "agendado" && item.publicar_em ? ` para ${dataPublicacao(item.publicar_em)}` : ""}
          {item.publicado_em ? ` · publicado em ${dataPublicacao(item.publicado_em)}` : ""}</p>
        {item.janelas && <ul className="board-windows">
          <Janela nome="D+7" janela={item.janelas.d7}/>
          <Janela nome="D+28" janela={item.janelas.d28}/>
        </ul>}
        <div className="board-actions">
          <Link className="btn" href={`${base}/producao#/producao?run=${encodeURIComponent(item.run_id)}`}>Ver execução</Link>
          {item.url && <Link className="btn" href={item.url + "#janelas"}>Ver resultado</Link>}
        </div>
      </li>)}
    </ul>
  </section>;
}
