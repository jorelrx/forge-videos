"use client";
import { useEffect, useState } from "react";
import type { YouTubeLogin } from "../lib/contracts";
import { studioRequest } from "../lib/api";

interface Tentativa { tentativa_id: string; login: YouTubeLogin }

export function VinculoCanal({ canalId, analytics = false, onComplete }: {
  canalId?: string; analytics?: boolean; onComplete?: () => void;
}) {
  const [tentativa, setTentativa] = useState<Tentativa | null>(null);
  const [erro, setErro] = useState("");
  const [iniciando, setIniciando] = useState(false);
  const id = tentativa?.tentativa_id;
  const status = tentativa?.login.status;
  useEffect(() => {
    if (!id || status === "falhou") return;
    if (status === "concluido") {
      if (onComplete) onComplete();
      else window.location.reload();
      return;
    }
    const controller = new AbortController();
    let timer: number;
    async function consultar() {
      try {
        const resultado = await studioRequest<Tentativa>("/api/youtube/login/" + encodeURIComponent(id!), {signal:controller.signal});
        if (!controller.signal.aborted) {
          setTentativa(resultado);
          if (resultado.login.status === "aguardando" || resultado.login.status === "inativo") timer = window.setTimeout(consultar, 1500);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setErro(error instanceof Error ? error.message : "Falha ao consultar autorização.");
          setTentativa(null);
        }
      }
    }
    timer = window.setTimeout(consultar, 1000);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [id, status, onComplete]);

  async function iniciar() {
    setErro("");
    setIniciando(true);
    try {
      setTentativa(await studioRequest<Tentativa>("/api/youtube/login", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({canal_id:canalId, analytics}),
      }));
    } catch (error) { setErro(error instanceof Error ? error.message : "Falha ao iniciar autorização."); }
    finally { setIniciando(false); }
  }

  const aguardando = tentativa && status !== "falhou" && status !== "concluido";
  return <div className="studio-vinculo">
    <button className="btn" type="button" disabled={Boolean(aguardando || iniciando)} onClick={iniciar}>
      {analytics ? "Habilitar indicadores" : canalId ? "Reconectar YouTube" : "Vincular canal"}
    </button>
    {aguardando && (tentativa.login.url
      ? <a className="btn btn-primary" href={tentativa.login.url} target="_blank" rel="noopener noreferrer">Autorizar no Google</a>
      : <span role="status">Preparando autorização…</span>)}
    {aguardando && <small>Autorize usando o mesmo perfil de navegador do Studio.</small>}
    {(erro || status === "falhou") && <p role="alert">{erro || tentativa?.login.erro || "Autorização interrompida."}</p>}
  </div>;
}
