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


def test_bootstrap_skips_apt_packages_without_installation_candidate():
    script = (PROJECT_ROOT / 'scripts' / 'bootstrap_dependencies.sh').read_text()
    assert 'apt_package_has_candidate()' in script
    assert 'apt-cache policy "$package"' in script
    assert 'apt-Paket $package ist in den aktiven Paketquellen nicht verfügbar; überspringe.' in script
    assert 'run_root apt-get install -y "$package"' in script


def test_bootstrap_builds_pigpio_from_source_when_daemon_is_missing():
    script = (PROJECT_ROOT / 'scripts' / 'bootstrap_dependencies.sh').read_text()
    assert 'install_pigpio_from_source_if_missing()' in script
    assert 'command -v pigpiod' in script
    assert 'trap \'rm -rf "$build_dir"\' RETURN' in script
    assert 'git clone --depth 1 https://github.com/joan2937/pigpio.git' in script
    assert 'run_root make install' in script
    assert 'install_pigpiod_service_if_missing' in script


def test_bootstrap_checks_systemd_units_by_exact_name():
    script = (PROJECT_ROOT / 'scripts' / 'bootstrap_dependencies.sh').read_text()
    assert 'systemd_unit_exists()' in script
    assert 'grep -Fxq "$unit_name"' in script
    assert 'systemd_unit_exists pigpiod.service' in script
    assert 'systemd_unit_exists "$SERVICE_NAME"' in script
