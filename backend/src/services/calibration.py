"""Residual calibration for scheduling upper limits ("排期上限").

A cap is issued and frozen per (report, order code) at intake time.  It adds a
one-sided residual quantile to the report's selected point model, so that a
roughly ``COVERAGE`` share of settled orders stay below their cap.  Residuals are
always ``actual - frozen point``; the stored point is never fed back into the
residual pool, so repeated calibrations cannot compound.

Calibration is group-conditional (Mondrian).  A crew's *own pool* is its live
settlements plus the rows the report already froze for it (its development-fold
and holdout predictions):

* At least ``MIN_CREW`` own rows — calibrate the crew on its own pool alone, so a
  persistently underestimated crew is lifted on its own and other crews are
  untouched.
* Between 1 and ``MIN_CREW - 1`` own rows — blend the own pool with the shared
  pool.  A crew's first settlement therefore still moves the *next* cap, while a
  single point cannot define the whole quantile by itself.
* No own rows at all — fall back to the shared pool: other crews' live
  settlements, or the out-of-sample residuals frozen in the report (development
  folds + holdout).  This keeps a cap available for a crew that has only just
  started.

Live settlements are read at issuance, so a settlement that arrives late is
picked up by the *next* new order while every already-issued cap stays frozen.
The order code being estimated is always excluded from every pool, so an order
never calibrates against itself.
"""
from math import ceil

COVERAGE = 0.9
MIN_GLOBAL = 3
MIN_CREW = 3
METHOD = 'residual-quantile-v1'


def coverage_quantile(values, coverage=COVERAGE):
    """Split-conformal one-sided quantile.

    The textbook rank is ``ceil((n + 1) * coverage)``; with few samples that rank
    exceeds ``n`` and formally needs ``+inf``.  We clamp to the largest observed
    residual instead: a finite, deliberately conservative cap is more useful for
    scheduling than refusing to quote one.  That also means small samples get the
    widest cushion.  Returns ``None`` for an empty pool.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = min(len(ordered), max(1, ceil((len(ordered) + 1) * coverage)))
    return ordered[rank - 1]


def _without(rows, order_code):
    return [row for row in rows if row['order_code'] != order_code]


def _quantile(rows, coverage):
    return coverage_quantile([row['residual'] for row in rows], coverage)


def _shared(settled, report_rows, coverage):
    if len(settled) >= MIN_GLOBAL:
        return 'settled', settled, _quantile(settled, coverage)
    return 'report', report_rows, _quantile(report_rows, coverage)


def build_calibration(settled, report_rows, crew, order_code, coverage=COVERAGE):
    """Assemble cap calibration for one order code and crew.

    Each row is ``{'order_code', 'crew', 'base', 'actual', 'residual'}``; ``base``
    is the frozen point the residual was measured against.
    """
    settled = _without(settled, order_code)
    report_rows = _without(report_rows, order_code)
    peers = [row for row in settled if row['crew'] != crew]
    peer_report = [row for row in report_rows if row['crew'] != crew]
    shared_source, shared_rows, shared_offset = _shared(peers, peer_report, coverage)
    shared_offset = shared_offset or 0.0

    crew_settled = [row for row in settled if row['crew'] == crew]
    crew_report = [row for row in report_rows if row['crew'] == crew]
    own = crew_settled + crew_report
    if len(own) >= MIN_CREW:
        scope, pool, source = 'crew', own, 'settled' if crew_settled else 'report'
    elif own:
        scope, pool = 'crew', own + shared_rows
        source = 'blend'
    else:
        scope, pool, source = 'shared', shared_rows, shared_source
    offset = _quantile(pool, coverage)
    offset = shared_offset if offset is None else offset
    uplift = max(0.0, offset - shared_offset) if scope == 'crew' else 0.0

    return {
        'method': METHOD,
        'coverage': coverage,
        'scope': scope,
        'source': source,
        'sample_count': len(pool),
        'sample_orders': [row['order_code'] for row in pool][:50],
        'offset': offset,
        'shared': {'source': shared_source, 'sample_count': len(shared_rows),
                   'offset': shared_offset},
        'crew': {
            'code': crew,
            'settled_count': len(crew_settled),
            'report_count': len(crew_report),
            'offset': offset if scope == 'crew' and source != 'blend' else None,
            'lifted': scope == 'crew' and uplift > 1e-9,
            'uplift': uplift,
        },
        'thresholds': {'shared': MIN_GLOBAL, 'crew': MIN_CREW},
    }


def upper_limit(point, calibration):
    """One-sided scheduling cap; never below the point estimate."""
    return max(point, point + calibration['offset'])


def _fold_rows(fold, key):
    return [{'order_code': row['code'], 'crew': fold['crew'], 'base': row[key],
             'actual': row['actual'], 'residual': row['actual'] - row[key]}
            for row in fold['predictions']]


def report_residuals(result):
    """Out-of-sample residuals frozen inside a report result (winning model only)."""
    key = 'lasso' if result['winner'] == 'lasso' else 'baseline'
    rows = [row for fold in result['folds'] for row in _fold_rows(fold, key)]
    rows.extend(_fold_rows(result['holdout'], key))
    return rows


def settled_rows(rows):
    return [{'order_code': row['order_code'], 'crew': row['crew'], 'base': row['base_hours'],
             'actual': row['actual_hours'], 'residual': row['actual_hours'] - row['base_hours'],
             'settled_at': row['settled_at']} for row in rows]
