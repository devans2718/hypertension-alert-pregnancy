"""Checks for the integrated eight-scenario synthetic BP generator."""
from datetime import datetime, timedelta
import pytest
from htn_alert.contract import Reading
from htn_alert.generator import SCENARIOS, generate_bp_readings, generate_cohort, summarize_cohort
from htn_alert.protocol import load_protocol
from htn_alert.rules import is_severe

START = datetime(2026, 10, 26, 8, 0)
PROTOCOL = load_protocol()

def make(scenario, seed=42, **kwargs):
    return generate_bp_readings('P-001', START, scenario=scenario, seed=seed, **kwargs)

def test_original_default_13_readings():
    r = make('non_hypertensive')
    assert len(r) == 13 and all(isinstance(x, Reading) for x in r)
    assert [x.time for x in r] == [START + timedelta(minutes=i) for i in range(0,181,15)]
    assert all(115 <= x.systolic <= 125 and 76 <= x.diastolic <= 84 for x in r)

def test_one_hour_five_readings():
    assert len(generate_bp_readings('P-001', START, duration_hours=1)) == 5

def test_reproducible():
    assert make('persistent_severe', 120) == make('persistent_severe', 120)

def test_all_eight_present():
    assert len(SCENARIOS) == len(set(SCENARIOS)) == 8

@pytest.mark.parametrize('scenario', SCENARIOS)
def test_chronological_and_patient_id(scenario):
    r = make(scenario)
    assert all(x.patient_id == 'P-001' for x in r)
    assert [x.time for x in r] == sorted({x.time for x in r})

@pytest.mark.parametrize('scenario', ('non_hypertensive', 'mild_hypertension', 'borderline_severe'))
def test_nosevere_categories(scenario):
    assert not any(is_severe(x, PROTOCOL) for x in make(scenario))

def test_mild_every_reading_hypertensive():
    assert all(x.systolic >= 140 or x.diastolic >= 90 for x in make('mild_hypertension'))

def test_persistent_repeat_at_ten():
    r = make('persistent_severe')
    severe = [x for x in r if is_severe(x, PROTOCOL)]
    assert len(severe) >= 2 and severe[1].time - severe[0].time == timedelta(minutes=10)

def test_transient_normal_repeat():
    r = make('nonpersistent_severe')
    first = next(i for i,x in enumerate(r) if is_severe(x, PROTOCOL))
    assert r[first+1].time - r[first].time == timedelta(minutes=10)
    assert not is_severe(r[first+1], PROTOCOL)

def test_recurrent_severe():
    r = make('recurrent_severe')
    severe = [x for x in r if is_severe(x, PROTOCOL)]
    assert len(severe) >= 3
    assert severe[-1].time - severe[0].time <= timedelta(minutes=60)

@pytest.mark.parametrize('subtype,delay', [('delayed', 16), ('missing_early', 30)])
@pytest.mark.parametrize('seed', [42, 43, 120, 121])
def test_delayed_recheck_has_no_early_reading(subtype, delay, seed):
    r=make('delayed_or_missing_repeat', seed, delayed_repeat_subtype=subtype)
    first = next(x for x in r if is_severe(x, PROTOCOL))
    following = next(x for x in r if x.time>first.time)
    assert following.time-first.time == timedelta(minutes=delay)
    assert not is_severe(following, PROTOCOL)


@pytest.mark.parametrize('seed', [42, 43])
def test_default_delayed_subtype_is_seed_independent(seed):
    assert make('delayed_or_missing_repeat', seed) == make(
        'delayed_or_missing_repeat', seed, delayed_repeat_subtype='delayed'
    )


@pytest.mark.parametrize('kwargs', [
    {'scenario': 'delayed_or_missing_repeat', 'delayed_repeat_subtype': 'unknown'},
    {'scenario': 'persistent_severe', 'delayed_repeat_subtype': 'delayed'},
])
def test_invalid_delayed_subtype_rejected(kwargs):
    with pytest.raises(ValueError, match='subtype'):
        generate_bp_readings('P-001', START, **kwargs)


def test_cohort_subtype_cycle_is_independent_of_seed():
    for seed in (42, 43):
        cohort = generate_cohort(patients_per_scenario=2, seed=seed)
        # The delayed family is seventh; its first two patients use both subtypes.
        for pid, delay in [('SIM-00013', 30), ('SIM-00014', 16)]:
            readings = cohort[pid]
            first = next(r for r in readings if is_severe(r, PROTOCOL))
            repeat = next(r for r in readings if r.time > first.time)
            assert repeat.time - first.time == timedelta(minutes=delay)


def test_default_cohort_matches_pre_refactor_observations():
    """Guard every default fixture and RNG draw against accidental model changes."""
    from hashlib import sha256

    cohort = generate_cohort()
    # Captured from PR #7 before this config/severity refactor (seed 42).
    assert sha256(repr(cohort).encode()).hexdigest() == (
        'b7506e069fe2d084ebdfe9fa6743ccf744110c643128d23bb6f593ee4283efd3'
    )

def test_spurious_is_ground_truth_only():
    r=make('spurious_severe')
    assert sum(is_severe(x, PROTOCOL) for x in r) == 1
    assert not hasattr(r[0], 'is_spurious')

def test_cohort_80_and_summary():
    c=generate_cohort()
    s=summarize_cohort(c)
    assert len(c)==80 and s['patients']==80
    assert s['patients_with_severe_readings']==50
    assert s['total_readings']>=80*13
    assert len(set(c))==80
    assert generate_cohort()==c

def test_5000_cohort_possible():
    c=generate_cohort(patients_per_scenario=625)
    assert len(c)==5000

@pytest.mark.parametrize('kwargs', [
    {'patient_id':''}, {'duration_hours':0}, {'interval_minutes':0},
    {'scenario':'not_real'}, {'duration_hours':1,'scenario':'persistent_severe'},
])
def test_invalid(kwargs):
    args=dict(patient_id='P-001',start_time=START)
    args.update(kwargs)
    with pytest.raises(ValueError):
        generate_bp_readings(**args)
