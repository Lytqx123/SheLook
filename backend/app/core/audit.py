"""AI 生成审计日志服务

提供：
- audit_operation(): 写入审计日志
- request_id 由 RequestIDMiddleware 统一注入，本模块只负责审计记录持久化
- query_audit_logs(): 按条件查询日志（供监管接口使用）
"""

import uuid

from app.core.logging import logger

# ---- 审计日志写入 ----

async def audit_operation(
    operation: str,
    *,
    request_id: str | None = None,
    product_id: int | None = None,
    scheme_id: int | None = None,
    image_id: int | None = None,
    model_name: str | None = None,
    prompt_hash: str | None = None,
    generation_params: dict | None = None,
    image_url: str | None = None,
    c2pa_manifest_present: bool = False,
    compliance_checks_passed: bool | None = None,
    status: str = "pending",
    error_message: str | None = None,
    duration_ms: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> int:
    """写入一条审计日志

    Returns:
        创建的 AuditLog.id
    """
    from app.db.session import async_session_factory
    from app.models.audit_log import AuditLog

    log = AuditLog(
        request_id=request_id or str(uuid.uuid4()),
        operation=operation,
        product_id=product_id,
        scheme_id=scheme_id,
        image_id=image_id,
        model_name=model_name,
        prompt_hash=prompt_hash,
        generation_params=generation_params,
        image_url=image_url,
        c2pa_manifest_present=c2pa_manifest_present,
        compliance_checks_passed=compliance_checks_passed,
        jurisdiction="EU-AI-Act,CN-DS-Regulation-2026",
        status=status,
        error_message=error_message,
        duration_ms=duration_ms,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    try:
        async with async_session_factory() as db:
            db.add(log)
            await db.flush()
            await db.commit()
            log_id = log.id
            logger.debug("审计日志已写入", log_id=log_id, operation=operation)
            return log_id
    except Exception as e:
        logger.error("审计日志写入失败", error=str(e), operation=operation)
        return -1


# ---- 审计日志查询 ----

async def query_audit_logs(
    *,
    request_id: str | None = None,
    image_id: int | None = None,
    operation: str | None = None,
    status: str | None = None,
    model_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """按条件查询审计日志

    用于监管接口 /api/audit/logs

    Returns:
        {"total": int, "items": [...], "limit": int, "offset": int}
    """
    from sqlalchemy import func, select

    from app.db.session import async_session_factory
    from app.models.audit_log import AuditLog

    async with async_session_factory() as db:
        query = select(AuditLog)

        if request_id:
            query = query.where(AuditLog.request_id == request_id)
        if image_id is not None:
            query = query.where(AuditLog.image_id == image_id)
        if operation:
            query = query.where(AuditLog.operation == operation)
        if status:
            query = query.where(AuditLog.status == status)
        if model_name:
            query = query.where(AuditLog.model_name == model_name)
        if start_date:
            query = query.where(AuditLog.created_at >= start_date)
        if end_date:
            query = query.where(AuditLog.created_at <= end_date)

        # 总数
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # 分页
        query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        items = result.scalars().all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": item.id,
                    "request_id": item.request_id,
                    "operation": item.operation,
                    "product_id": item.product_id,
                    "scheme_id": item.scheme_id,
                    "image_id": item.image_id,
                    "model_name": item.model_name,
                    "prompt_hash": item.prompt_hash,
                    "image_url": item.image_url,
                    "c2pa_manifest_present": item.c2pa_manifest_present,
                    "compliance_checks_passed": item.compliance_checks_passed,
                    "status": item.status,
                    "error_message": item.error_message,
                    "duration_ms": item.duration_ms,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in items
            ],
        }
