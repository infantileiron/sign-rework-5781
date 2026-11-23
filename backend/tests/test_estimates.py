"""Integration tests for issued caps against a live PostgreSQL.

Skipped automatically unless the connection env vars are set, so the pure unit
tests keep running without a database.
"""
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytestmark = pytest.mark.skipif(
    not os.getenv('POSTGRES_HOST'), reason='需要设置 POSTGRES_HOST 等连接变量才能跑数据库测试')

from src.config.database import connect, migrate  # noqa: E402
from src.constants.domain import Status  # noqa: E402
from src.models import reports  # noqa: E402
from src.services import estimates as forecast  # noqa: E402
from src.services.comparison import compare  # noqa: E402
from src.services.reports import enqueue  # noqa: E402


ACTOR = 'analyst@bridge.test'


@pytest.fixture(scope='module')
def report():
    migrate()
    with connect() as db:
        created = enqueue(db, 1, 'G06', ACTOR)
        frozen = db.execute('SELECT snapshot, fingerprint FROM reports WHERE id = %s', (created['id'],)).fetchone()
        reports.finish_job(db, created['id'], Status.SUCCEEDED, compare(frozen['snapshot']), None)
        db.commit()
        report_id = created['id']
    with connect() as db:
        yield reports.get_report(db, report_id, False)
    with connect() as db:
        db.execute('DELETE FROM estimates WHERE report_id = %s', (report_id,))
        db.execute('DELETE FROM orders WHERE code LIKE %s', ('QY-99%',))
        db.execute('DELETE FROM reports WHERE id = %s', (report_id,))


def issue(report, code, crew='G05', minutes=5.5, shots=22, switches=2):
    with connect() as db:
        return forecast.issue(db, report, {'order_code': code, 'crew': crew, 'minutes': minutes,
                                           'shots': shots, 'switches': switches}, ACTOR)


def settle(code, crew, hours, minutes=5.0, shots=20, switches=1):
    with connect() as db:
        db.execute('''INSERT INTO orders (code, title, crew, minutes, shots, switches, hours)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET hours = EXCLUDED.hours, settled_at = now()''',
                   (code, f'测试结算 {code}', crew, minutes, shots, switches, hours))


def test_first_cap_has_an_upper_limit_before_any_settlement(report):
    row = issue(report, 'QY-9901')
    assert row['upper_hours'] >= row['point_hours']
    assert row['calibration']['source'] == 'report'
    assert row['calibration']['sample_count'] > 0


def test_retry_keeps_the_original_cap(report):
    first = issue(report, 'QY-9902')
    again = issue(report, 'QY-9902')
    assert again['reused'] is True
    assert again['upper_hours'] == first['upper_hours']
    assert again['calibration'] == first['calibration']


def test_conflicting_retry_is_rejected(report):
    issue(report, 'QY-9903')
    with pytest.raises(Exception) as caught:
        issue(report, 'QY-9903', minutes=9.9)
    assert getattr(caught.value, 'status', None) == 409


def test_late_settlements_calibrate_the_next_cap(report):
    first = issue(report, 'QY-9910', minutes=5.0, shots=20)
    settle('QY-9910', 'G05', hours=9.0)                       # settled after issue
    next_cap = issue(report, 'QY-9911', minutes=5.1, shots=21)
    with connect() as db:
        frozen = forecast.lookup(db, report, 'QY-9910')
    assert frozen['calibration'] == first['calibration']       # the earlier cap never changes
    # The late settlement is now part of G05's own pool for the next cap, and its
    # large positive residual pushes the offset up.
    assert next_cap['calibration']['source'] == 'settled'
    assert next_cap['calibration']['crew']['settled_count'] >= 1
    assert next_cap['calibration']['offset'] > frozen['calibration']['offset']


def test_settlement_retry_is_counted_once(report):
    settle('QY-9920', 'G05', hours=8.0)
    issue(report, 'QY-9920', minutes=5.2, shots=21)
    with connect() as db:
        before = db.execute("SELECT count(*) AS n FROM estimates WHERE report_id = %s AND order_code = 'QY-9920'",
                            (report['id'],)).fetchone()['n']
        db.execute("UPDATE orders SET hours = 8.0, settled_at = now() WHERE code = 'QY-9920'")
        same = db.execute("SELECT count(*) AS n FROM estimates WHERE report_id = %s AND order_code = 'QY-9920'",
                          (report['id'],)).fetchone()['n']
        db.execute("UPDATE orders SET hours = 8.4, settled_at = now() WHERE code = 'QY-9920'")
        revised = db.execute("SELECT count(*) AS n FROM estimates WHERE report_id = %s AND order_code = 'QY-9920'",
                             (report['id'],)).fetchone()['n']
    assert before == 1 and same == 1 and revised == 1


def test_underestimating_crew_is_lifted_individually(report):
    for index in range(3):
        code = f'QY-993{index}'
        settle(code, 'G05', hours=11.0)
        issue(report, code, crew='G05', minutes=5.0 + index * 0.1, shots=20 + index)
    settle('QY-9940', 'G02', hours=5.0)
    issue(report, 'QY-9940', crew='G02', minutes=5.0, shots=20)
    lifted = issue(report, 'QY-9941', crew='G05', minutes=5.5, shots=23)
    aligned = issue(report, 'QY-9942', crew='G02', minutes=5.5, shots=23)
    assert lifted['calibration']['scope'] == 'crew'
    assert lifted['calibration']['crew']['lifted'] is True
    assert lifted['calibration']['offset'] > aligned['calibration']['offset']


def test_reconciliation_matches_settlements(report):
    issue(report, 'QY-9950', minutes=5.0, shots=20)
    settle('QY-9950', 'G05', hours=6.0)
    with connect() as db:
        result = forecast.reconcile(db, report)
    item = next(row for row in result['items'] if row['order_code'] == 'QY-9950')
    assert item['settled'] is True
    assert item['actual_hours'] == 6.0
    assert item['signed_error'] == pytest.approx(6.0 - item['point_hours'])
    assert item['within_cap'] == (6.0 <= item['upper_hours'])
    pending = next(row for row in result['items'] if row['order_code'] == 'QY-9901')
    assert pending['settled'] is False and pending['within_cap'] is None
