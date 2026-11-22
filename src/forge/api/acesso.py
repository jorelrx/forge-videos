from fastapi import Request

from forge.api.errors import not_found
from forge.api.routes.sessao import canal_unico, conta_atual, exigir_canal


def canal_da_consulta(request: Request) -> str:
    canal = request.query_params.get("canal_id")
    return exigir_canal(request, canal) if canal is not None else canal_unico(request)


def canal_da_run(request: Request, run_id: str) -> str:
    conta_atual(request)
    db = request.app.state.services.commands.db
    with db.connection() as conn:
        row = conn.execute("SELECT canal_id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row or not row["canal_id"]:
        not_found("run", run_id)
    canal = row["canal_id"]
    if request.query_params.get("canal_id", canal) != canal:
        not_found("run", run_id)
    return exigir_canal(request, canal)


def autorizar_producao(request: Request) -> None:
    run_id = request.path_params.get("run_id")
    if request.url.path == "/api/events/stream":
        run_id = request.query_params.get("run_id")
    if run_id:
        canal_da_run(request, run_id)
    elif "artifact_id" in request.path_params:
        conta_atual(request)  # O handler resolve a execução antes de abrir o arquivo.
    else:
        canal_da_consulta(request)
