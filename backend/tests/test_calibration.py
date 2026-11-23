"""Unit tests for residual calibration (no database required)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.calibration import (  # noqa: E402
    COVERAGE, build_calibration, coverage_quantile, report_residuals, settled_rows, upper_limit,
)


def row(code, crew, base, actual):
    return {'order_code': code, 'crew': crew, 'base': base, 'actual': actual, 'residual': actual - base}


def test_quantile_is_one_sided_and_clamps_small_samples():
    assert coverage_quantile([]) is None
    assert coverage_quantile([4.0]) == 4.0                       # clamped, not infinity
    assert coverage_quantile([1.0, 2.0, 3.0]) == 3.0
    values = list(range(1, 21))
    assert coverage_quantile(values) == 19                       # ceil(21 * 0.9) -> 19th of 20


def test_upper_limit_never_below_point():
    calibration = build_calibration([], [row('R1', 'G01', 4.0, 5.0)], 'G06', 'NEW')
    assert upper_limit(3.0, calibration) >= 3.0
    negative = {'offset': -2.0}
    assert upper_limit(3.0, negative) == 3.0


def test_empty_settlements_fall_back_to_report_samples():
    report_rows = [row(f'R{i}', 'G01', 4.0, 4.8) for i in range(5)]
    calibration = build_calibration([], report_rows, 'G06', 'NEW')
    assert calibration['scope'] == 'shared'
    assert calibration['source'] == 'report'
    assert calibration['offset'] == pytest.approx(0.8)


def test_excludes_the_order_being_estimated():
    settled = [row('SELF', 'G05', 5.0, 99.0)]                     # a huge self residual
    calibration = build_calibration(settled, [row('R1', 'G01', 4.0, 5.0)], 'G05', 'SELF')
    assert calibration['scope'] == 'shared'
    assert calibration['sample_count'] == 1
    assert calibration['offset'] == 1.0


def test_crew_is_lifted_on_its_own_residuals():
    settled = [row(f'A{i}', 'G05', 5.0, 5.0 + off) for i, off in enumerate([2.5, 3.0, 3.2, 2.8])]
    settled += [row(f'B{i}', 'G02', 5.0, 5.0 + res) for i, res in enumerate([0.1, -0.2, 0.2, 0.0])]

    underestimating = build_calibration(settled, [], 'G05', 'NEW')
    aligned = build_calibration(settled, [], 'G02', 'NEW')

    assert underestimating['scope'] == 'crew'
    assert underestimating['crew']['lifted'] is True
    assert upper_limit(6.0, underestimating) > upper_limit(6.0, aligned)
    assert aligned['scope'] == 'crew'
    assert aligned['crew']['lifted'] is False
    assert aligned['offset'] == pytest.approx(0.2)


def test_a_first_settlement_moves_the_next_cap_by_blending():
    # G03 has two settlements (below MIN_CREW), so it is blended with the shared
    # pool. Its large residuals still push the offset above the shared-only value.
    settled = [row(f'A{i}', 'G05', 5.0, 5.0 + off) for i, off in enumerate([0.1, 0.2, 0.3])]
    settled += [row('C1', 'G03', 5.0, 10.0), row('C2', 'G03', 5.0, 10.0)]  # 2 settlements, +5 each
    calibration = build_calibration(settled, [], 'G03', 'NEW')
    assert calibration['scope'] == 'crew'
    assert calibration['crew']['settled_count'] == 2
    assert calibration['offset'] > calibration['shared']['offset']
    assert calibration['offset'] == pytest.approx(5.0)


def test_no_own_rows_falls_back_to_report_samples():
    report_rows = [row(f'R{i}', 'G05', 5.0, 6.0 + i) for i in range(4)]
    calibration = build_calibration([], report_rows, 'G05', 'NEW')
    assert calibration['scope'] == 'crew'
    assert calibration['source'] == 'report'
    assert calibration['crew']['settled_count'] == 0


def test_crew_with_no_own_rows_uses_shared_floor():
    # G03 has no rows of its own; it borrows the shared floor of the other crews.
    settled = [row(f'B{i}', 'G02', 5.0, 5.0 + res) for i, res in enumerate([0.5, 0.4, 0.6])]
    calibration = build_calibration(settled, [], 'G03', 'NEW')
    assert calibration['scope'] == 'shared'
    assert calibration['source'] == 'settled'
    assert calibration['crew']['settled_count'] == 0
    assert calibration['offset'] == pytest.approx(calibration['shared']['offset'])


def test_report_residuals_use_the_winning_model_only():
    def fold(crew, code, actual, lasso, baseline):
        return {'crew': crew, 'predictions': [{'code': code, 'actual': actual, 'lasso': lasso, 'baseline': baseline}]}

    result = {'winner': 'lasso',
              'folds': [fold('G01', 'A', 7.0, 6.0, 3.0)],
              'holdout': fold('G06', 'B', 8.0, 5.0, 1.0)}
    residuals = report_residuals(result)
    assert [item['residual'] for item in residuals] == [1.0, 3.0]
    assert {item['order_code'] for item in residuals} == {'A', 'B'}


def test_settled_rows_measure_against_frozen_point():
    rows = [{'order_code': 'A', 'crew': 'G05', 'base_hours': 5.0, 'actual_hours': 8.0, 'settled_at': None}]
    assert settled_rows(rows)[0]['residual'] == 3.0
    assert COVERAGE == 0.9
