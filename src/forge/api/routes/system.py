from fastapi import APIRouter

system_router = APIRouter()

# Stubs — rotas completas não implementadas ainda (Task 5 parcial)
@system_router.get("/api/services")
async def list_services():
    return {"stub": True, "message": "routes incompletas — Task 5 parcial"}

@system_router.get("/api/config/effective")
async def effective_config():
    return {"stub": True, "message": "redaction de chaves não implementada ainda"}
