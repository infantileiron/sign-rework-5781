from psycopg.types.json import Jsonb

from src.utils.errors import Problem


COLUMNS = ('id, report_id, order_code, crew, minutes, shots, switches, point_hours, point_model, '
           'upper_hours, coverage, calibration, created_by, created_at')


def list_estimates(db, report_id):
    return db.execute(f'SELECT {COLUMNS} FROM estimates WHERE report_id = %s ORDER BY created_at, id',
                      (report_id,)).fetchall()


def get_estimate(db, report_id, order_code):
    row = db.execute(f'SELECT {COLUMNS} FROM estimates WHERE report_id = %s AND order_code = %s',
                     (report_id, order_code)).fetchone()
    if not row:
        raise Problem(404, '该报告下没有此工单的试估记录')
    return row


def settled_residuals(db, report_id):
    """Issued caps whose order code now has a settlement.

    Joining on the order code (not on the estimate row) means a settlement that
    arrives late — after the cap was issued — is still picked up the next time a
    cap is issued, while every already-issued cap stays frozen.  A repeated
    settlement write updates the same order row instead of adding a second
    residual, and the unique key on (report_id, order_code) keeps one estimate —
    and therefore one residual — per code.
    """
    return db.execute('''SELECT estimates.order_code, estimates.crew, estimates.point_hours AS base_hours,
            estimates.created_at AS issued_at, orders.hours AS actual_hours, orders.settled_at
        FROM estimates JOIN orders ON orders.code = estimates.order_code
        WHERE estimates.report_id = %s
        ORDER BY estimates.order_code''', (report_id,)).fetchall()


def insert_estimate(db, values):
    """Persist one cap per (report, order code); a retry returns the frozen original."""
    row = db.execute('''INSERT INTO estimates (report_id, order_code, crew, minutes, shots, switches,
            point_hours, point_model, upper_hours, coverage, calibration, created_by)
        VALUES (%(report_id)s, %(order_code)s, %(crew)s, %(minutes)s, %(shots)s, %(switches)s,
                %(point_hours)s, %(point_model)s, %(upper_hours)s, %(coverage)s, %(calibration)s, %(created_by)s)
        ON CONFLICT (report_id, order_code) DO NOTHING
        RETURNING ''' + COLUMNS,
        {**values, 'calibration': Jsonb(values['calibration'])}).fetchone()
    if row:
        return row, False
    existing = get_estimate(db, values['report_id'], values['order_code'])
    if not same_request(existing, values):
        raise Problem(409, '该工单已在本报告发过排期上限；已发出的上限照旧，请换用工单号试估')
    return existing, True


def same_request(existing, values):
    return (existing['crew'] == values['crew'] and existing['minutes'] == values['minutes']
            and existing['shots'] == values['shots'] and existing['switches'] == values['switches'])


def reconciliation(db, report_id):
    return db.execute('''SELECT estimates.order_code, estimates.crew, estimates.minutes, estimates.shots,
            estimates.switches, estimates.point_hours, estimates.point_model, estimates.upper_hours,
            estimates.coverage, estimates.calibration, estimates.created_at AS issued_at,
            orders.title, orders.hours AS actual_hours, orders.settled_at
        FROM estimates LEFT JOIN orders ON orders.code = estimates.order_code
        WHERE estimates.report_id = %s
        ORDER BY estimates.created_at, estimates.id''', (report_id,)).fetchall()
