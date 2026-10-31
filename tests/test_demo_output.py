"""Demonstration labels must describe the target actually used by each run."""

import hashlib
import re
import runpy
from dataclasses import asdict
from pathlib import Path

import pytest

from htn_alert.cohort_evaluation import evaluate_cohort
from htn_alert.protocol import DEFAULT_PATH, load_protocol
from htn_alert.workflow import PROVIDER_PATHWAYS, simulate_workflow

SOURCE_DIR = Path(__file__).resolve().parents[1] / 'src' / 'htn_alert'
TIMING_DEMOS = ('workflow', 'paired_simulation', 'cohort_evaluation', 'sensitivity_analysis')

# Captured before the display fix. Default text, values and spacing must survive.
DEFAULT_OUTPUT_HASHES = {
    'generator': '2faff935eef8dd160c7a6f930be8fee8f2a36f87c4a653a38073588aad927915',
    'workflow': '6ddd491399e94355f1564ce0056ebd4314261cd3ab13e35a334f10e7c174608d',
    'paired_simulation': 'e83745bdf95a3660e71b176ab6e2c8f5367632c651d5466dd33663a481de4c20',
    'cohort_evaluation': 'a9fe7f33ead04de577b4fdbdee3d56e1d6daa2219be25c7cb22ac87f0703f128',
    'sensitivity_analysis': 'a28a161c3a2add8238aa0cf7f591537b4a9c0e7e1cb4e62faa59fdf603784f24',
}


def configured_protocol(tmp_path, repeat_minutes, treatment_minutes):
    """Load test-only values without editing the shared clinical configuration."""
    text = DEFAULT_PATH.read_text().replace(
        'min_minutes = 15', f'min_minutes = {repeat_minutes}'
    ).replace('target_minutes = 60', f'target_minutes = {treatment_minutes}')
    path = tmp_path / 'protocol.toml'
    path.write_text(text)
    return load_protocol(path)


def run_demo(module):
    # Executes the real __main__ block without a subprocess or editing config.
    return runpy.run_path(str(SOURCE_DIR / f'{module}.py'), run_name='__main__')


@pytest.mark.parametrize('module', TIMING_DEMOS)
@pytest.mark.parametrize('repeat_minutes,treatment_minutes', [(20, 35), (20.5, 35.5)])
def test_demo_labels_match_nondefault_protocol(
    tmp_path, monkeypatch, capsys, module, repeat_minutes, treatment_minutes,
):
    protocol = configured_protocol(tmp_path, repeat_minutes, treatment_minutes)
    loads = []

    def load_once():
        loads.append(protocol)
        assert len(loads) == 1, 'Labels and calculations must share one loaded protocol.'
        return protocol

    monkeypatch.setattr('htn_alert.protocol.load_protocol', load_once)
    namespace = run_demo(module)
    output = capsys.readouterr().out
    assert loads == [protocol]
    assert 'within 60 minutes' not in output
    target = f'{treatment_minutes:g}'

    if module in ('workflow', 'paired_simulation'):
        readings = namespace['patient_readings' if module == 'workflow' else 'readings']
        expected = [
            str(simulate_workflow(readings, mode=mode, provider_pathway=pathway,
                protocol=protocol).within_treatment_target)
            for pathway in PROVIDER_PATHWAYS for mode in ('baseline', 'tool')
        ]
        assert re.findall(rf'within {re.escape(target)} minutes: (True|False)', output) == expected
        if module == 'workflow':
            label = f'{repeat_minutes:g}-minute target:'
            assert output.count(label) == 6
            assert '15-minute target:' not in output
            result = namespace['result']
            assert result.recheck_plan.target_time == result.first_severe_time + protocol.repeat_min
            assert f'{label} {result.recheck_plan.target_time}' in output
    elif module == 'cohort_evaluation':
        evaluation = namespace['evaluation']
        expected = evaluate_cohort(namespace['cohort'], protocol=protocol)
        # run_path defines the demo's dataclass in __main__; compare its data.
        assert asdict(evaluation) == asdict(expected)
        assert f'Baseline medication within {target} minutes: {expected.supported_baseline_within_60}' in output
        assert f'OB-Response medication within {target} minutes: {expected.supported_tool_within_60}' in output
        assert f'- Medication within {target} minutes is a timing indicator' in output
    else:
        assert f'Within {target} B/T' in output
        assert f'- Within-{target} counts are not the full SMFM patient-level rate.' in output
        assert 'Within 60 B/T' not in output
        assert 'Within-60 counts' not in output
        lines = output.splitlines()
        for row in namespace['rows']:
            expected = evaluate_cohort(namespace['cohort'], prompt_effect=row.prompt_effect,
                protocol=protocol)
            counts = f'{expected.supported_baseline_within_60}/{expected.supported_tool_within_60}'
            line = next(line for line in lines if line.strip().startswith(f'{row.prompt_effect:.0%} '))
            assert line.split()[-1] == counts
            assert row.baseline_within_60 == expected.supported_baseline_within_60
            assert row.tool_within_60 == expected.supported_tool_within_60


def test_35_minute_label_does_not_claim_a_60_minute_result(tmp_path, monkeypatch, capsys):
    protocol = configured_protocol(tmp_path, 15, 35)
    monkeypatch.setattr('htn_alert.protocol.load_protocol', lambda: protocol)
    namespace = run_demo('workflow')
    output = capsys.readouterr().out
    baseline = simulate_workflow(namespace['patient_readings'], protocol=protocol)
    assert baseline.treatment_minutes == 44
    assert baseline.within_treatment_target is False
    assert baseline.treatment_minutes <= 60
    assert 'Medication within 35 minutes: False' in output
    assert 'Medication within 60 minutes:' not in output


@pytest.mark.parametrize('module', DEFAULT_OUTPUT_HASHES)
def test_default_demo_output_is_unchanged(module, capsys):
    run_demo(module)
    output = capsys.readouterr().out
    assert hashlib.sha256(output.encode()).hexdigest() == DEFAULT_OUTPUT_HASHES[module]
