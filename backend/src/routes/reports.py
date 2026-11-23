from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from src.config.database import connect
from src.constants.domain import Role
from src.controllers.auth import allow, current_user
from src.models import audit, reports
from src.schemas.inputs import EstimateInput, RunInput
from src.services import estimates as forecast
from src.services.reports import enqueue, require_result, rows_csv


router = APIRouter(prefix='/api/reports')
ReportID = Annotated[int, Path(gt=0, le=9223372036854775807)]
OrderCode = Annotated[str, Path(pattern=r'^[A-Z][A-Z0-9-]{2,19}$')]


@router.get('')
def index(user=Depends(current_user)):
    with connect() as db:
        return reports.list_reports(db, user['role'] == Role.VIEWER)


@router.post('', status_code=202)
def start(form: RunInput, user=Depends(allow(Role.ANALYST))):
    with connect() as db:
        return enqueue(db, form.plan_id, form.holdout, user['email'])


@router.get('/{report_id}')
def detail(report_id: ReportID, user=Depends(current_user)):
    with connect() as db:
        return reports.get_report(db, report_id, user['role'] == Role.VIEWER)


@router.post('/{report_id}/publish')
def publish(report_id: ReportID, user=Depends(allow(Role.OWNER))):
    with connect() as db:
        report, changed = reports.publish_report(db, report_id, user['email'])
        if changed:
            audit.record(db, user['email'], 'report.publish', report_id)
        return report


@router.post('/{report_id}/estimate')
def estimate(report_id: ReportID, form: EstimateInput, user=Depends(current_user)):
    """Issue and freeze a point estimate plus a scheduling upper limit."""
    report = detail(report_id, user)
    require_result(report)
    with connect() as db:
        row = forecast.issue(db, report, form.model_dump(), user['email'])
    return row


@router.get('/{report_id}/estimates')
def estimate_list(report_id: ReportID, user=Depends(current_user)):
    report = detail(report_id, user)
    require_result(report)
    with connect() as db:
        return forecast.issued(db, report)


@router.get('/{report_id}/estimates/reconcile')
def estimate_reconcile(report_id: ReportID, user=Depends(current_user)):
    report = detail(report_id, user)
    require_result(report)
    with connect() as db:
        return forecast.reconcile(db, report)


@router.get('/{report_id}/estimates/{order_code}')
def estimate_detail(report_id: ReportID, order_code: OrderCode, user=Depends(current_user)):
    report = detail(report_id, user)
    require_result(report)
    with connect() as db:
        return forecast.lookup(db, report, order_code)


@router.get('/{report_id}/export')
def export(report_id: ReportID, user=Depends(current_user)):
    content = rows_csv(detail(report_id, user))
    return Response(content, media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="sign-rework-{report_id}.csv"'})
