from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from ...db import DatabaseType, db_manager
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...utils.datetime import get_timestamp

router = APIRouter(prefix="/avanpost", tags=["Avanpost"])


class ExecuteQueryRequest(BaseModel):
    query: str = Field(..., description="SQL запрос", min_length=1)
    params: dict[str, Any] | None = Field(None, description="Параметры запроса")


class ExecuteProcedureRequest(BaseModel):
    procedure_name: str = Field(..., description="Имя хранимой процедуры")
    params: dict[str, Any] | None = Field(None, description="Параметры процедуры")


@router.post("/query", summary="Выполнить SQL запрос")
@log_exceptions(api_logger)
async def execute_query(request: ExecuteQueryRequest) -> dict[str, Any]:
    """Выполнение произвольного SQL запроса к MSSQL"""
    try:
        async with db_manager.get_session("avanpost") as session:
            result = await session.execute(text(request.query), request.params or {})
            rows = result.fetchall()

            # Преобразование в список словарей
            if rows:
                columns = result.keys()
                result_list = [dict(zip(columns, row, strict=False)) for row in rows]
            else:
                result_list = []

            await session.commit()

            return {"success": True, "rows": len(result_list), "result": result_list, "timestamp": get_timestamp()}
    except Exception as e:
        api_logger.error(f"❌ Avanpost query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}") from e


@router.post("/procedure", summary="Выполнить хранимую процедуру")
@log_exceptions(api_logger)
async def execute_procedure(request: ExecuteProcedureRequest) -> dict[str, Any]:
    """Выполнение хранимой процедуры в MSSQL"""
    try:
        # Формирование вызова процедуры
        if request.params:
            param_placeholders = ", ".join([f":{key}" for key in request.params])
            query = f"EXEC {request.procedure_name} {param_placeholders}"
        else:
            query = f"EXEC {request.procedure_name}"

        async with db_manager.get_session("avanpost") as session:
            result = await session.execute(text(query), request.params or {})
            rows = result.fetchall()

            if rows:
                columns = result.keys()
                result_list = [dict(zip(columns, row, strict=False)) for row in rows]
            else:
                result_list = []

            await session.commit()

            return {"success": True, "rows": len(result_list), "result": result_list, "timestamp": get_timestamp()}
    except Exception as e:
        api_logger.error(f"❌ Avanpost procedure failed: {e}")
        raise HTTPException(status_code=500, detail=f"Procedure failed: {str(e)}") from e


@router.get("/status", summary="Статус Avanpost")
@log_exceptions(api_logger)
async def get_mssql_status() -> dict[str, Any]:
    """Получение статуса подключения к Avanpost"""
    try:
        # Проверяем, зарегистрирована ли MSSQL
        avanpost_engine = db_manager.get_engine_by_type(DatabaseType.MSSQL)

        if not avanpost_engine:
            return {
                "enabled": False,
                "configured": False,
                "message": "Avanpost is not configured",
                "timestamp": get_timestamp(),
            }

        connected = await db_manager.check_connection("avanpost")
        stats = await db_manager.get_stats()

        return {
            "enabled": True,
            "configured": True,
            "connected": connected,
            "stats": stats,
            "timestamp": get_timestamp(),
        }
    except Exception as e:
        api_logger.error(f"❌ Failed to get Avanpost status: {e}")
        return {"enabled": False, "error": str(e), "timestamp": get_timestamp()}
