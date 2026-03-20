from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select
from sqlalchemy import func as sa_func
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.database import get_session
from app.models.core import Project, CronJob, CronLog, SystemSetting, TaskLog, CardIndex
from croniter import croniter

router = APIRouter(tags=["CronJobs"])

# ==========================================
# CronJob Schemas
# ==========================================
class CronJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    system_instruction: Optional[str] = None
    prompt_template: Optional[str] = None
    is_enabled: Optional[bool] = None
    target_list_id: Optional[int] = None  # 0 = 清除（回到預設 Scheduled）

class CronJobCreateRequest(BaseModel):
    project_id: int
    name: str
    description: Optional[str] = None
    cron_expression: str = "0 0 * * *"
    system_instruction: Optional[str] = None
    prompt_template: str = ""
    target_list_id: Optional[int] = None  # 目標列表，None=Scheduled


# ==========================================
# CronJob Routes
# ==========================================
@router.get("/cron-jobs/", response_model=List[CronJob])
def read_cron_jobs(project_id: Optional[int] = None, session: Session = Depends(get_session)):
    # 回傳所有 CronJob，不再過濾 is_enabled
    query = select(CronJob)
    if project_id:
        query = query.where(CronJob.project_id == project_id)
    return session.exec(query).all()


@router.patch("/cron-jobs/{job_id}", response_model=CronJob)
def update_cron_job(job_id: int, update_data: CronJobUpdate, session: Session = Depends(get_session)):
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    cron_changed = False
    for field in ["name", "description", "cron_expression", "system_instruction", "prompt_template", "is_enabled"]:
        val = getattr(update_data, field)
        if val is not None:
            if field == "cron_expression" and val != job.cron_expression:
                cron_changed = True
            setattr(job, field, val)
    # 目標列表：0 = 清除，正數 = 設定
    if update_data.target_list_id is not None:
        job.target_list_id = update_data.target_list_id if update_data.target_list_id != 0 else None
    # cron 表達式或啟用狀態改變時，重算下次執行時間
    if cron_changed or (update_data.is_enabled is not None):
        from app.core.cron_poller import _calculate_next_time, _get_system_timezone
        tz_name = _get_system_timezone(session)
        next_time = _calculate_next_time(job.cron_expression, tz_name)
        if next_time:
            job.next_scheduled_at = next_time
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post("/cron-jobs/", response_model=CronJob)
def create_cron_job(data: CronJobCreateRequest, session: Session = Depends(get_session)):
    project = session.get(Project, data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 計算下次執行時間（用系統時區解析 cron 表達式）
    next_time = None
    try:
        tz_setting = session.get(SystemSetting, "timezone")
        tz_name = tz_setting.value if tz_setting and tz_setting.value else "Asia/Taipei"
        local_tz = ZoneInfo(tz_name)
        now_local = datetime.now(local_tz)
        cron = croniter(data.cron_expression, now_local)
        next_local = cron.get_next(datetime)
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=local_tz)
        next_time = next_local.astimezone(timezone.utc)
    except Exception:
        pass
    job = CronJob(
        project_id=data.project_id,
        name=data.name,
        description=data.description,
        cron_expression=data.cron_expression,
        system_instruction=data.system_instruction,
        prompt_template=data.prompt_template,
        target_list_id=data.target_list_id,
        next_scheduled_at=next_time,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post("/cron-jobs/fix-schedules")
def fix_cron_schedules(session: Session = Depends(get_session)):
    """修復所有排程的 next_scheduled_at（以系統時區重新計算下次執行時間）"""
    from app.core.cron_poller import _calculate_next_time, _get_system_timezone
    tz_name = _get_system_timezone(session)
    jobs = session.exec(select(CronJob).where(CronJob.is_enabled == True)).all()
    fixed_count = 0
    for job in jobs:
        try:
            next_time = _calculate_next_time(job.cron_expression, tz_name)
            if next_time:
                job.next_scheduled_at = next_time
                session.add(job)
                fixed_count += 1
        except Exception as e:
            pass
    session.commit()
    return {"ok": True, "fixed_count": fixed_count}


@router.post("/cron-jobs/{job_id}/trigger")
def trigger_cron_job(job_id: int, session: Session = Depends(get_session)):
    """手動觸發 CronJob，建立待執行卡片"""
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")

    from app.core.cron_poller import create_card_for_cron_job
    card_id, error = create_card_for_cron_job(session, job, update_next_time=False)

    if error:
        raise HTTPException(status_code=409, detail=error)

    return {"ok": True, "card_id": card_id, "message": f"已手動觸發「{job.name}」"}


@router.get("/cron-jobs/{job_id}")
def get_cron_job(job_id: int, session: Session = Depends(get_session)):
    """取得單一排程詳情"""
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    return job


@router.delete("/cron-jobs/{job_id}")
def delete_cron_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(CronJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="CronJob not found")
    if job.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete a system cron job")
    session.delete(job)
    session.commit()
    return {"ok": True}


# ==========================================
# CronJob Logs
# ==========================================
@router.get("/cron-jobs/{job_id}/logs")
def list_cron_logs(job_id: int, limit: int = 50, offset: int = 0, session: Session = Depends(get_session)):
    """取得特定排程的執行記錄"""
    logs = session.exec(
        select(CronLog)
        .where(CronLog.cron_job_id == job_id)
        .order_by(CronLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    total = session.exec(
        select(sa_func.count()).select_from(CronLog).where(CronLog.cron_job_id == job_id)
    ).one()
    return {"items": logs, "total": total}


# ==========================================
# TaskLog（任務執行記錄）
# ==========================================
@router.get("/task-logs/")
def list_task_logs(
    request: Request,
    member_id: Optional[int] = None,
    project_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """取得任務執行記錄（可按成員/專案篩選，並套用可見性過濾）"""
    from app.api.deps import get_visibility_filter
    visible_project_ids, _ = get_visibility_filter(request, session)

    query = select(TaskLog)
    count_query = select(sa_func.count()).select_from(TaskLog)

    if member_id is not None:
        query = query.where(TaskLog.member_id == member_id)
        count_query = count_query.where(TaskLog.member_id == member_id)

    # 按專案過濾（透過 CardIndex join）
    if project_id is not None:
        query = query.join(CardIndex, TaskLog.card_id == CardIndex.card_id).where(CardIndex.project_id == project_id)
        count_query = count_query.join(CardIndex, TaskLog.card_id == CardIndex.card_id).where(CardIndex.project_id == project_id)
    elif visible_project_ids is not None:
        # 非 admin / 未登入 → 只看可見專案的 logs
        query = query.join(CardIndex, TaskLog.card_id == CardIndex.card_id).where(CardIndex.project_id.in_(visible_project_ids))
        count_query = count_query.join(CardIndex, TaskLog.card_id == CardIndex.card_id).where(CardIndex.project_id.in_(visible_project_ids))

    logs = session.exec(query.order_by(TaskLog.created_at.desc()).offset(offset).limit(limit)).all()
    total = session.exec(count_query).one()
    return {"items": logs, "total": total}


@router.get("/task-logs/{log_id}")
def get_task_log(log_id: int, session: Session = Depends(get_session)):
    """取得單筆任務執行記錄詳情"""
    log = session.get(TaskLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="TaskLog not found")
    return log


# ==========================================
# CronLog（排程執行記錄）
# ==========================================
@router.get("/cron-logs/")
def list_all_cron_logs(limit: int = 50, offset: int = 0, project_id: Optional[int] = None, session: Session = Depends(get_session)):
    """取得所有排程執行記錄（可按專案篩選）"""
    query = select(CronLog)
    count_query = select(sa_func.count()).select_from(CronLog)
    if project_id is not None:
        query = query.where(CronLog.project_id == project_id)
        count_query = count_query.where(CronLog.project_id == project_id)
    logs = session.exec(query.order_by(CronLog.created_at.desc()).offset(offset).limit(limit)).all()
    total = session.exec(count_query).one()
    return {"items": logs, "total": total}


@router.get("/cron-logs/{log_id}")
def get_cron_log(log_id: int, session: Session = Depends(get_session)):
    """取得單筆排程執行記錄詳情"""
    log = session.get(CronLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="CronLog not found")
    return log
