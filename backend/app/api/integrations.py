"""Tenant-admin management API for Dianxiaomi integration configuration."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserInfo, has_permission, require_auth
from app.core.logging import logger
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.integration import DianxiaomiConnection, IntegrationSyncRun
from app.schemas.integration import (
    DianxiaomiConfigCheckResponse,
    DianxiaomiConnectionCreate,
    DianxiaomiConnectionResponse,
    DianxiaomiConnectionUpdate,
    IntegrationSyncRunResponse,
    IntegrationSyncStartResponse,
)
from app.services.integration_credentials import (
    CredentialCipherError,
    decrypt_credentials,
    encrypt_credentials,
)

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])


async def require_integration_manager(user: UserInfo = Depends(require_auth)) -> UserInfo:
    if not (user.role == "admin" or has_permission(user, "tenant:manage")):
        raise HTTPException(status_code=403, detail="需要租户集成配置权限")
    return user


def _response(connection: DianxiaomiConnection) -> DianxiaomiConnectionResponse:
    return DianxiaomiConnectionResponse(
        id=connection.id,
        tenant_id=connection.tenant_id,
        display_name=connection.display_name,
        merchant_reference=connection.merchant_reference,
        api_base_url=connection.api_base_url,
        shop_references=[str(item) for item in (connection.shop_references or [])],
        sync_scopes=list(connection.sync_scopes or []),
        sync_interval_minutes=connection.sync_interval_minutes,
        status=connection.status,
        credentials_configured=bool(connection.credentials_encrypted),
        credentials_fingerprint=(connection.credentials_fingerprint or "")[:12] or None,
        config_version=connection.config_version,
        last_sync_at=connection.last_sync_at,
        last_sync_status=connection.last_sync_status,
        last_sync_error=connection.last_sync_error,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _sync_run_response(run: IntegrationSyncRun) -> IntegrationSyncRunResponse:
    return IntegrationSyncRunResponse(
        id=run.id,
        connection_id=run.connection_id,
        trigger=run.trigger,
        status=run.status,
        requested_scopes=list(run.requested_scopes or []),
        config_version=run.config_version,
        records_received=run.records_received,
        records_applied=run.records_applied,
        error_message=run.error_message,
        cursor_before=run.cursor_before,
        cursor_after=run.cursor_after,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


async def _connection_or_404(
    db: AsyncSession,
    connection_id: str,
    tenant_id: str,
) -> DianxiaomiConnection:
    connection = await db.scalar(
        select(DianxiaomiConnection).where(
            DianxiaomiConnection.id == connection_id,
            DianxiaomiConnection.tenant_id == tenant_id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="店小秘连接不存在")
    return connection


def _audit_configuration_change(
    db: AsyncSession,
    *,
    tenant_id: str,
    connection_id: str,
    action: str,
    user_id: str,
) -> None:
    """Record metadata only: neither credentials nor raw connection payloads."""
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            request_id=str(uuid4()),
            operation="integration_config",
            model_name="dianxiaomi",
            generation_params={
                "connection_id": connection_id,
                "action": action,
                "actor_id": user_id,
            },
            status="success",
        )
    )


@router.get("/dianxiaomi", response_model=list[DianxiaomiConnectionResponse])
async def list_dianxiaomi_connections(
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> list[DianxiaomiConnectionResponse]:
    result = await db.execute(
        select(DianxiaomiConnection)
        .where(DianxiaomiConnection.tenant_id == user.tenant_id)
        .order_by(DianxiaomiConnection.updated_at.desc())
    )
    return [_response(connection) for connection in result.scalars()]


@router.post("/dianxiaomi", response_model=DianxiaomiConnectionResponse, status_code=201)
async def create_dianxiaomi_connection(
    body: DianxiaomiConnectionCreate,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> DianxiaomiConnectionResponse:
    try:
        ciphertext, fingerprint = encrypt_credentials(body.credentials.model_dump())
    except CredentialCipherError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    connection = DianxiaomiConnection(
        tenant_id=user.tenant_id,
        display_name=body.display_name,
        merchant_reference=body.merchant_reference,
        api_base_url=body.api_base_url,
        shop_references=body.shop_references or None,
        sync_scopes=body.sync_scopes,
        sync_interval_minutes=body.sync_interval_minutes,
        status="configured",
        credentials_encrypted=ciphertext,
        credentials_fingerprint=fingerprint,
        created_by=user.user_id,
        updated_by=user.user_id,
    )
    db.add(connection)
    await db.flush()
    _audit_configuration_change(
        db,
        tenant_id=user.tenant_id,
        connection_id=connection.id,
        action="created",
        user_id=user.user_id,
    )
    await db.flush()
    await db.refresh(connection)
    return _response(connection)


@router.patch("/dianxiaomi/{connection_id}", response_model=DianxiaomiConnectionResponse)
async def update_dianxiaomi_connection(
    connection_id: str,
    body: DianxiaomiConnectionUpdate,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> DianxiaomiConnectionResponse:
    connection = await _connection_or_404(db, connection_id, user.tenant_id)
    changed = False
    fields_set = body.model_fields_set

    for field in (
        "display_name",
        "merchant_reference",
        "api_base_url",
        "shop_references",
        "sync_scopes",
        "sync_interval_minutes",
    ):
        if field in fields_set:
            setattr(connection, field, getattr(body, field))
            changed = True

    if body.credentials is not None:
        try:
            ciphertext, fingerprint = encrypt_credentials(body.credentials.model_dump())
        except CredentialCipherError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        connection.credentials_encrypted = ciphertext
        connection.credentials_fingerprint = fingerprint
        changed = True

    if body.enabled is not None:
        connection.status = "configured" if body.enabled else "disabled"
        changed = True

    if changed:
        connection.config_version += 1
        connection.updated_by = user.user_id
        _audit_configuration_change(
            db,
            tenant_id=user.tenant_id,
            connection_id=connection.id,
            action="updated",
            user_id=user.user_id,
        )
        await db.flush()
        await db.refresh(connection)
    return _response(connection)


@router.post(
    "/dianxiaomi/{connection_id}/validate",
    response_model=DianxiaomiConfigCheckResponse,
)
async def validate_dianxiaomi_connection(
    connection_id: str,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> DianxiaomiConfigCheckResponse:
    connection = await _connection_or_404(db, connection_id, user.tenant_id)
    if not connection.credentials_encrypted or not connection.api_base_url:
        connection.status = "incomplete"
        connection.last_sync_error = "请先配置 HTTPS API 地址和店小秘授权凭据"
        await db.flush()
        return DianxiaomiConfigCheckResponse(
            connection_id=connection.id,
            status="incomplete",
            message=connection.last_sync_error,
            config_version=connection.config_version,
        )

    try:
        decrypt_credentials(connection.credentials_encrypted)
    except CredentialCipherError as exc:
        connection.status = "incomplete"
        connection.last_sync_error = str(exc)
        await db.flush()
        return DianxiaomiConfigCheckResponse(
            connection_id=connection.id,
            status="incomplete",
            message=str(exc),
            config_version=connection.config_version,
        )

    connection.status = "ready_for_vendor_validation"
    connection.last_sync_error = None
    _audit_configuration_change(
        db,
        tenant_id=user.tenant_id,
        connection_id=connection.id,
        action="configuration_validated",
        user_id=user.user_id,
    )
    await db.flush()
    return DianxiaomiConfigCheckResponse(
        connection_id=connection.id,
        status="ready_for_vendor_validation",
        message=(
            "配置与加密凭据校验通过。店小秘实际接口字段、签名和授权范围需要依据"
            "贵司已获授权的开放平台文档完成连接器验证，当前不会伪造外部请求。"
        ),
        config_version=connection.config_version,
    )


@router.get(
    "/dianxiaomi/{connection_id}/sync-runs",
    response_model=list[IntegrationSyncRunResponse],
)
async def list_dianxiaomi_sync_runs(
    connection_id: str,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationSyncRunResponse]:
    await _connection_or_404(db, connection_id, user.tenant_id)
    runs = (
        await db.execute(
            select(IntegrationSyncRun)
            .where(IntegrationSyncRun.connection_id == connection_id)
            .order_by(IntegrationSyncRun.started_at.desc())
            .limit(50)
        )
    ).scalars()
    return [_sync_run_response(run) for run in runs]


@router.post(
    "/dianxiaomi/{connection_id}/sync",
    response_model=IntegrationSyncStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_dianxiaomi_sync(
    connection_id: str,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> IntegrationSyncStartResponse:
    connection = await _connection_or_404(db, connection_id, user.tenant_id)
    if connection.status not in {"configured", "ready_for_vendor_validation"}:
        raise HTTPException(status_code=422, detail="连接未就绪或已停用，不能启动同步")
    run = IntegrationSyncRun(
        tenant_id=user.tenant_id,
        connection_id=connection.id,
        trigger="manual",
        status="queued",
        requested_scopes=list(connection.sync_scopes or []),
        config_version=connection.config_version,
    )
    db.add(run)
    await db.flush()
    _audit_configuration_change(
        db,
        tenant_id=user.tenant_id,
        connection_id=connection.id,
        action="sync_queued",
        user_id=user.user_id,
    )
    # Commit before publishing so a fast worker cannot observe a missing run.
    await db.commit()
    from app.tasks.integration_task import sync_dianxiaomi_connection

    try:
        sync_dianxiaomi_connection.delay(user.tenant_id, run.id)
    except Exception as exc:
        # The run is already committed, so preserve an auditable terminal
        # state instead of leaving a permanently queued row when Redis/Celery
        # is unavailable between the API and the worker.
        run.status = "dispatch_failed"
        run.error_message = "同步任务未能投递到队列；请在队列恢复后重新发起。"
        connection.last_sync_status = run.status
        connection.last_sync_error = run.error_message
        _audit_configuration_change(
            db,
            tenant_id=user.tenant_id,
            connection_id=connection.id,
            action="sync_dispatch_failed",
            user_id=user.user_id,
        )
        await db.commit()
        logger.exception("店小秘同步任务投递失败", run_id=run.id, connection_id=connection.id)
        raise HTTPException(status_code=503, detail=run.error_message) from exc
    return IntegrationSyncStartResponse(
        run_id=run.id,
        status="queued",
        message="店小秘同步任务已排队；供应商契约未就绪时将明确标记为待授权，不会伪造同步结果。",
    )


@router.delete("/dianxiaomi/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dianxiaomi_connection(
    connection_id: str,
    user: UserInfo = Depends(require_integration_manager),
    db: AsyncSession = Depends(get_db),
) -> Response:
    connection = await _connection_or_404(db, connection_id, user.tenant_id)
    _audit_configuration_change(
        db,
        tenant_id=user.tenant_id,
        connection_id=connection.id,
        action="deleted",
        user_id=user.user_id,
    )
    await db.delete(connection)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
