from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_installs_complete_requirements_file_into_venv():
    script = (PROJECT_ROOT / 'scripts' / 'bootstrap_dependencies.sh').read_text()
    assert 'python -m pip install -r "$PROJECT_ROOT/requirements.txt"' in script
    assert 'while IFS= read -r requirement' in script
    assert 'done < "$PROJECT_ROOT/requirements.txt"' in script


def test_bootstrap_verifies_all_runtime_requirement_imports():
    script = (PROJECT_ROOT / 'scripts' / 'bootstrap_dependencies.sh').read_text()
    for requirement, module in {
        'Flask': 'flask',
        'RPi.GPIO': 'RPi.GPIO',
        'spidev': 'spidev',
        'pigpio': 'pigpio',
    }.items():
        assert f"'{requirement}': '{module}'" in script
    assert 'return 1' in script


def test_start_warns_for_every_pager_hardware_import():
    script = (PROJECT_ROOT / 'start.sh').read_text()
    for requirement, module in {
        'RPi.GPIO': 'RPi.GPIO',
        'pigpio': 'pigpio',
        'spidev': 'spidev',
    }.items():
        assert f"'{requirement}': '{module}'" in script
