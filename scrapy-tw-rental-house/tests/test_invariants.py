'''invariants／compare_invariants 的離線測試（L3 drift 斷言，dx 3-3）'''
import pytest

from scrapy_twrh.cli import runner
from scrapy_twrh.spiders.enums import BuildingType, PropertyType


def make_generic(**overrides):
    base = {
        'floor': 3,
        'total_floor': 4,
        'building_type': BuildingType.電梯大樓,
        'property_type': PropertyType.獨立套房,
        'is_rooftop': False,
        'rough_coordinate': (23.9, 121.6),
        'floor_ping': 8.0,
        'monthly_price': 8000,
    }
    base.update(overrides)
    return base


def make_baseline(**overrides):
    invariants = runner.invariants([make_generic() for _ in range(10)])
    invariants.update(overrides)
    return {
        'scope': 'test',
        'min_samples': 5,
        'tolerance': {'median': 1, 'share': 0.10, 'fill': 0.05},
        'invariants': invariants,
    }


def test_invariants_basic_shape():
    generics = [make_generic() for _ in range(9)] + [
        make_generic(property_type=PropertyType.整層住家,
                     building_type=BuildingType.公寓, is_rooftop=True)]
    result = runner.invariants(generics)
    assert result['n'] == 10
    assert result['median_floor'] == 3
    assert result['median_total_floor'] == 4
    assert result['share_電梯大樓'] == 0.9
    assert result['share_公寓'] == 0.1
    assert result['share_套房'] == 0.9
    assert result['share_整層住家'] == 0.1
    assert result['rooftop_rate'] == 0.1
    assert result['fill_monthly_price'] == 1.0


def test_invariants_empty():
    assert runner.invariants([]) == {'n': 0}


def test_compare_passes_when_identical():
    generics = [make_generic() for _ in range(10)]
    results, passed, skipped = runner.compare_invariants(
        runner.invariants(generics), make_baseline())
    assert skipped is None
    assert passed
    assert all(ok for _, ok, *_ in results)


def test_compare_fails_on_share_drift():
    # baseline 全是套房，現況全是整層住家 → share 漂移超過 ±0.10
    generics = [make_generic(property_type=PropertyType.整層住家)
                for _ in range(10)]
    results, passed, _ = runner.compare_invariants(
        runner.invariants(generics), make_baseline())
    assert not passed
    failed_keys = {key for key, ok, *_ in results if not ok}
    assert 'share_套房' in failed_keys
    assert 'share_整層住家' in failed_keys


def test_compare_fails_when_fill_improves():
    # 雙向斷言：填充率「變好」也算漂移
    baseline = make_baseline(fill_rough_coordinate=0.9)
    generics = [make_generic() for _ in range(10)]  # fill = 1.0
    results, passed, _ = runner.compare_invariants(
        runner.invariants(generics), baseline)
    assert not passed
    assert {key for key, ok, *_ in results if not ok} == {'fill_rough_coordinate'}


def test_compare_skips_below_min_samples():
    generics = [make_generic() for _ in range(3)]
    results, passed, skipped = runner.compare_invariants(
        runner.invariants(generics), make_baseline())
    assert results == []
    assert passed
    assert 'min_samples' in skipped
