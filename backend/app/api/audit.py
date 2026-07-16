"""审计日志 API —— 合规回溯用的，监管那边会查"""

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.logging import logger

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/logs")
async def get_audit_logs(
    request: Request,
    request_id: str | None = Query(None, description="请求唯一ID"),
    image_id: int | None = Query(None, description="关联图片ID"),
    operation: str | None = Query(None, description="操作类型: generate/evaluate/review/export"),
    status: str | None = Query(None, description="操作状态: pending/success/failed"),
    model_name: str | None = Query(None, description="AI 模型名称"),
    start_date: str | None = Query(None, description="开始日期 ISO格式"),
    end_date: str | None = Query(None, description="结束日期 ISO格式"),
    limit: int = Query(100, ge=1, le=1000, description="每页条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """审计日志分页查询，按条件筛选"""
    from app.core.audit import query_audit_logs

    try:
        result = await query_audit_logs(
            request_id=request_id,
            image_id=image_id,
            operation=operation,
            status=status,
            model_name=model_name,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        return result
    except Exception as e:
        logger.error("审计日志查询失败", error=str(e))
        raise HTTPException(status_code=500, detail="审计日志查询失败") from e


@router.get("/logs/{log_id}")
async def get_audit_log_detail(
    log_id: int,
    request: Request,
):
    """查单条日志详情"""
    from sqlalchemy import select

    from app.db.session import async_session_factory
    from app.models.audit_log import AuditLog

    async with async_session_factory() as db:
        result = await db.execute(select(AuditLog).where(AuditLog.id == log_id))
        log = result.scalar_one_or_none()
        if not log:
            raise HTTPException(status_code=404, detail=f"审计日志 #{log_id} 不存在")

        return {
            "id": log.id,
            "request_id": log.request_id,
            "operation": log.operation,
            "product_id": log.product_id,
            "scheme_id": log.scheme_id,
            "image_id": log.image_id,
            "model_name": log.model_name,
            "prompt_hash": log.prompt_hash,
            "generation_params": log.generation_params,
            "image_url": log.image_url,
            "c2pa_manifest_present": log.c2pa_manifest_present,
            "compliance_checks_passed": log.compliance_checks_passed,
            "jurisdiction": log.jurisdiction,
            "status": log.status,
            "error_message": log.error_message,
            "duration_ms": log.duration_ms,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }


@router.get("/trace/{request_id}")
async def trace_by_request_id(
    request_id: str,
    request: Request,
):
    """按 request_id 追踪全链路 —— API → Celery Task → DB"""
    from app.core.audit import query_audit_logs

    result = await query_audit_logs(request_id=request_id)
    return {
        "request_id": request_id,
        "total": result["total"],
        "items": result["items"],
    }
