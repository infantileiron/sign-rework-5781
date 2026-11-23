from src.models import audit, estimates
from src.services.calibration import (COVERAGE, METHOD, build_calibration, report_residuals,
                                      settled_rows, upper_limit)
from src.services.comparison import predict
from src.services.reports import require_result


def issue(db, report, form, actor):
    """Freeze a point estimate and scheduling upper limit for one order code."""
    result = require_result(report)
    point = predict(result, form)
    settled = settled_rows(estimates.settled_residuals(db, report['id']))
    calibration = build_calibration(settled, report_residuals(result), form['crew'],
                                    form['order_code'], COVERAGE)
    values = {
        'report_id': report['id'],
        'order_code': form['order_code'],
        'crew': form['crew'],
        'minutes': form['minutes'],
        'shots': form['shots'],
        'switches': form['switches'],
        'point_hours': point['hours'],
        'point_model': result['winner'],
        'upper_hours': upper_limit(point['hours'], calibration),
        'coverage': COVERAGE,
        'calibration': calibration,
        'created_by': actor,
    }
    row, reused = estimates.insert_estimate(db, values)
    if not reused:
        audit.record(db, actor, 'estimate.issue', f"{report['id']}:{form['order_code']}")
    return {**row, 'reused': reused, 'point': point}


def issued(db, report):
    """Caps issued under a report together with the frozen point and its calibration."""
    rows = estimates.list_estimates(db, report['id'])
    return {'report_id': report['id'], 'method': METHOD, 'coverage': COVERAGE,
            'estimates': [present(row) for row in rows]}


def present(row):
    return {
        'order_code': row['order_code'], 'crew': row['crew'], 'point_hours': row['point_hours'],
        'point_model': row['point_model'], 'upper_hours': row['upper_hours'],
        'coverage': row['coverage'], 'calibration': row['calibration'],
        'created_by': row['created_by'], 'created_at': row['created_at'],
    }


def reconcile(db, report):
    """Match issued caps against the settlement table by order code."""
    rows = estimates.reconciliation(db, report['id'])
    items = []
    for row in rows:
        actual = row['actual_hours']
        settled = actual is not None
        error = actual - row['point_hours'] if settled else None
        items.append({
            'order_code': row['order_code'], 'title': row['title'], 'crew': row['crew'],
            'minutes': row['minutes'], 'shots': row['shots'], 'switches': row['switches'],
            'point_hours': row['point_hours'], 'point_model': row['point_model'],
            'upper_hours': row['upper_hours'], 'coverage': row['coverage'],
            'calibration': row['calibration'], 'issued_at': row['issued_at'],
            'actual_hours': actual, 'settled_at': row['settled_at'], 'settled': settled,
            'signed_error': error,
            'abs_error': abs(error) if settled else None,
            'within_cap': (actual <= row['upper_hours']) if settled else None,
        })
    scored = [item for item in items if item['settled']]
    return {
        'report_id': report['id'],
        'items': items,
        'summary': {
            'issued': len(items),
            'settled': len(scored),
            'pending': len(items) - len(scored),
            'covered': sum(1 for item in scored if item['within_cap']),
            'coverage': (sum(1 for item in scored if item['within_cap']) / len(scored)) if scored else None,
            'mae': (sum(item['abs_error'] for item in scored) / len(scored)) if scored else None,
            'mean_signed_error': (sum(item['signed_error'] for item in scored) / len(scored)) if scored else None,
        },
    }


def lookup(db, report, order_code):
    row = estimates.get_estimate(db, report['id'], order_code)
    return present(row)
