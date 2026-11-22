"use client";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { IconArrowRight } from "./icons";
import { Sidebar } from "./sidebar";
import { DashboardProvider } from "./dashboard-provider";
import { ApiError, cancelarRequisicoes, SESSAO_EXPIRADA, studioRequest } from "../lib/api";
import { VinculoCanal } from "./vinculo-canal";

interface Conta { id: string; nome: string; avatar: string | null }
interface Canal { thumbnail?: string | null; id: string; titulo: string; conectado: boolean }
interface Acesso { conta: Conta; canais: Canal[]; ultimo_canal_id: string | null }

export function destinoInicial(canais: Canal[], ultimo: string | null) {
  return canais.length === 1 ? canais[0].id : canais.find(item => item.id === ultimo)?.id;
}

const caminhoCanal = (id: string) => "/canais/" + encodeURIComponent(id);

export function SessaoStudio({canalId, children}: {canalId?: string; children?: ReactNode}) {
  return <Entrada key={canalId ?? ""} canalId={canalId}>{children}</Entrada>;
}

function Entrada({ canalId, children }: {canalId?: string; children?: ReactNode}) {
  const pathname = usePathname();
  const router = useRouter();
  const [acesso, setAcesso] = useState<Acesso | null>(null);
  const [anonimo, setAnonimo] = useState(false);
  const [erro, setErro] = useState("");
  const [versao, setVersao] = useState(0);
  const [ocupado, setOcupado] = useState(false);
  const revalidar = useCallback(() => {
    setAnonimo(false);
    setErro("");
    setVersao(n => n + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const expirar = () => {
      cancelarRequisicoes();
      setAcesso(null);
      setErro("");
      setAnonimo(true);
    };
    const restaurar = (evento: PageTransitionEvent) => { if (evento.persisted) revalidar(); };
    const outraAba = (evento: StorageEvent) => { if (evento.key === "forge:sessao") revalidar(); };
    window.addEventListener(SESSAO_EXPIRADA, expirar);
    window.addEventListener("pagehide", cancelarRequisicoes);
    window.addEventListener("pageshow", restaurar);
    window.addEventListener("storage", outraAba);
    async function carregar() {
      try {
        const conta = await studioRequest<Conta>("/api/sessao", {signal:controller.signal});
        const lista = await studioRequest<Omit<Acesso,"conta">>("/api/canais", {signal:controller.signal});
        if (controller.signal.aborted) return;
        const inicial = destinoInicial(lista.canais, lista.ultimo_canal_id);
        if (!canalId && inicial) { window.location.replace(caminhoCanal(inicial)); return; }
        setAcesso({conta,...lista});
      } catch (error) {
        if (controller.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) return;
        if (error instanceof ApiError && error.failure.status === 401) expirar();
        else setErro("Falha ao consultar a sessão.");
      }
    }
    void carregar();
    return () => {
      controller.abort();
      cancelarRequisicoes();
      window.removeEventListener(SESSAO_EXPIRADA, expirar);
      window.removeEventListener("pagehide", cancelarRequisicoes);
      window.removeEventListener("pageshow", restaurar);
      window.removeEventListener("storage", outraAba);
    };
  }, [canalId, versao, revalidar]);

  useEffect(() => {
    if (!acesso) return;
    const controller = new AbortController();
    async function verificar() {
      try {
        const conta = await studioRequest<Conta>("/api/sessao", {signal:controller.signal});
        if (conta.id !== acesso!.conta.id) {cancelarRequisicoes();setAcesso(null);revalidar();return;}
        const lista = await studioRequest<Omit<Acesso,"conta">>("/api/canais", {signal:controller.signal});
        if (!controller.signal.aborted) setAcesso({conta, ...lista});
      } catch { /* 401 é tratado pelo evento de sessão. Falhas de rede mantêm o estado atual. */ }
    }
    window.addEventListener("focus", verificar);
    return () => {controller.abort();window.removeEventListener("focus",verificar);};
  }, [acesso,revalidar]);

  async function selecionar(id: string) {
    if (!id) return;
    setOcupado(true);
    try {
      await studioRequest("/api/sessao/canal", {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({canal_id:id})});
      router.push(caminhoCanal(id));
    } catch { setErro("Falha ao selecionar canal."); }
    finally { setOcupado(false); }
  }
  async function sair() {
    setOcupado(true);
    try {
      await studioRequest("/api/sessao/sair", {method:"POST"});
      window.dispatchEvent(new Event(SESSAO_EXPIRADA));
      try { localStorage.setItem("forge:sessao", crypto.randomUUID()); } catch { /* Armazenamento opcional. */ }
    } catch { setErro("Falha ao sair. Tente novamente."); }
    finally { setOcupado(false); }
  }

  if (!acesso) {
    const retorno = typeof window === "undefined" ? "/" : location.pathname + location.search + location.hash;
    return <main className="studio-entry"><div className="entry-card">
      <span className="brand-mark" aria-hidden="true">F</span>
      <div><h1>Forge Studio</h1><p>Produção, publicação e desempenho dos seus canais.</p></div>
      {anonimo ? <a className="btn btn-primary" href={"/api/sessao/google?retorno=" + encodeURIComponent(retorno)}>Entrar com Google <IconArrowRight size={16}/></a> :
      erro ? <><p role="alert">{erro}</p><button className="btn" onClick={revalidar}>Tentar novamente</button></> : <p role="status">Abrindo Studio…</p>}
    </div></main>;
  }
  const atual = acesso.canais.find(c => c.id === canalId);
  const base = atual && caminhoCanal(atual.id);
  const producao = !!base && pathname === base + "/producao";

  async function desvincular(id: string) {
    if (!window.confirm("Desvincular este canal da sua conta?")) return;
    try {
      await studioRequest("/api/youtube/channels/" + encodeURIComponent(id) + "/disconnect", {method: "POST"});
      revalidar();
    } catch {
      setErro("Falha ao desvincular canal.");
    }
  }

  return <div className="channel-studio" key={acesso.conta.id}>
    <header className="channel-header">
      {!base && <b>Forge Studio</b>}
      {acesso.canais.length > 0 && <label className="channel-picker">
        {atual?.thumbnail && <img className="channel-avatar" alt="" src={atual.thumbnail}/>}
        <span>Canal</span>
        <select className="select" value={atual?.id ?? ""} onChange={e => void selecionar(e.target.value)} disabled={ocupado}>
          {!atual && <option value="">Selecione um canal</option>}
          {acesso.canais.map(c => <option key={c.id} value={c.id}>{c.titulo}</option>)}
        </select>
      </label>}
      {atual && <details className="channel-settings">
        <summary>Gerenciar canais</summary>
        <div className="channel-settings-panel">
          <VinculoCanal onComplete={revalidar}/>
          <button className="btn" type="button" onClick={() => void desvincular(atual.id)}>Desvincular canal atual</button>
        </div>
      </details>}
      <span className="studio-account">{acesso.conta.avatar && <img src={acesso.conta.avatar} referrerPolicy="no-referrer" alt=""/>}<span>{acesso.conta.nome}</span></span>
      <button type="button" className="btn" onClick={sair} disabled={ocupado}>Sair</button>
    </header>
    {erro && <p className="app-alert" role="alert">{erro}</p>}
    {atual && base ? <DashboardProvider key={atual.id}><div className={producao ? "channel-production" : "channel-body"}>
      {producao ? null : <Sidebar channelBase={base} boardAtivo={pathname === base + "/proximo-video"}/>}
      <div className="channel-content">
        {!atual.conectado && <aside className="channel-notice">Conexão do YouTube expirada. <VinculoCanal canalId={atual.id} onComplete={revalidar}/></aside>}
        {children}
      </div>
    </div></DashboardProvider> : <main className="studio-entry"><div className="entry-card">
      <h1>{canalId ? "Canal sem acesso" : acesso.canais.length ? "Escolha um canal" : "Vincule seu canal do YouTube"}</h1>
      {canalId && <a href="/">Voltar aos canais autorizados</a>}
      <VinculoCanal onComplete={revalidar}/>
    </div></main>}
  </div>;
}
