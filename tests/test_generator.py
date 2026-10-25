"""Checks for the integrated eight-scenario synthetic BP generator."""
from datetime import datetime, timedelta
import pytest
from htn_alert.contract import Reading
from htn_alert.generator import SCENARIOS, generate_bp_readings, generate_cohort, summarize_cohort, is_severe

START = datetime(2026, 10, 26, 8, 0)

def make(scenario, seed=42):
    return generate_bp_readings('P-001', START, scenario=scenario, seed=seed)

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
    assert not any(is_severe(x.systolic,x.diastolic) for x in make(scenario))

def test_mild_every_reading_hypertensive():
    assert all(x.systolic >= 140 or x.diastolic >= 90 for x in make('mild_hypertension'))

def test_persistent_repeat_at_ten():
    r = make('persistent_severe')
    severe = [x for x in r if is_severe(x.systolic,x.diastolic)]
    assert len(severe) >= 2 and severe[1].time - severe[0].time == timedelta(minutes=10)

def test_transient_normal_repeat():
    r = make('nonpersistent_severe')
    first = next(i for i,x in enumerate(r) if is_severe(x.systolic,x.diastolic))
    assert r[first+1].time - r[first].time == timedelta(minutes=10)
    assert not is_severe(r[first+1].systolic,r[first+1].diastolic)

def test_recurrent_severe():
    r = make('recurrent_severe')
    severe = [x for x in r if is_severe(x.systolic,x.diastolic)]
    assert len(severe) >= 3
    assert severe[-1].time - severe[0].time <= timedelta(minutes=60)

def test_delayed_recheck_has_no_early_reading():
    for seed,delay in ((42,16),(43,30)):
        r=make('delayed_or_missing_repeat',seed)
        first = next(x for x in r if is_severe(x.systolic,x.diastolic))
        following = next(x for x in r if x.time>first.time)
        assert following.time-first.time == timedelta(minutes=delay)
        assert not is_severe(following.systolic,following.diastolic)

def test_spurious_is_ground_truth_only():
    r=make('spurious_severe')
    assert sum(is_severe(x.systolic,x.diastolic) for x in r) == 1
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
