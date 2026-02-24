"""
Battery Test Logic
All pass/fail, capacity calculation, and health checks.
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

from core.config import (
    BATTERY_CHEMISTRIES, DEFAULT_CHEMISTRY, DEFAULT_RATED_CAPACITY_AH,
    DEFAULT_PASS_THRESHOLD_PCT, CELL_IMBALANCE_WARNING_V,
    CELL_IMBALANCE_ALERT_V, MIN_START_VOLTAGE
)


# ── Enums ─────────────────────────────────────────────────────────────────────

class TestStatus(Enum):
    IDLE        = 'idle'
    PRE_CHECK   = 'pre_check'
    TESTING     = 'testing'
    COMPLETE    = 'complete'
    ABORTED     = 'aborted'

class TestResult(Enum):
    PENDING  = 'Pending'
    PASS     = 'PASS'
    FAIL     = 'FAIL'
    OVERRIDE = 'Override'   # User manually set pass/fail


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class PreCheckResult:
    all_cells_found:   bool = False
    cells_charged:     bool = False
    cells_balanced:    bool = False
    cell_count:        int  = 0
    min_voltage:       float = 0.0
    max_voltage:       float = 0.0
    spread:            float = 0.0
    messages:          List[str] = field(default_factory=list)

    @property
    def passed(self):
        return self.all_cells_found and self.cells_charged and self.cells_balanced


@dataclass
class CellSample:
    """One data point per cell per second"""
    timestamp:  float
    voltages:   List[float]
    current_ma: float = 0.0


@dataclass
class TestSession:
    """Complete test session data"""
    serial_number:       str   = ''
    chemistry:           str   = DEFAULT_CHEMISTRY
    rated_capacity_ah:   float = DEFAULT_RATED_CAPACITY_AH
    pass_threshold_pct:  float = DEFAULT_PASS_THRESHOLD_PCT

    # New tracking fields
    tech_initials:       str   = ''
    mfg_date:            str   = ''
    battery_age:         str   = ''

    # Test lifecycle
    status:              TestStatus  = TestStatus.IDLE
    result:              TestResult  = TestResult.PENDING
    override_reason:     str         = ''
    stop_reason:         str         = ''    # Tracks exact reason for stopping
    start_time:          Optional[float] = None
    end_time:            Optional[float] = None

    # Raw data (recorded every second, full discharge)
    samples:             List[CellSample] = field(default_factory=list)

    # Moving average buffers for smoothing (last 5 samples)
    voltage_buffer:      List[List[float]] = field(default_factory=list)  # [[v1,v2,...,v14], ...]
    current_buffer:      List[float] = field(default_factory=list)         # [i1, i2, i3, i4, i5]

    # Capacity (calculated independently of BMS)
    calculated_capacity_ah: float = 0.0
    last_current_ma:         float = 0.0
    last_sample_time:        Optional[float] = None

    # BMS reported values (for reference)
    bms_initial_soc:     int   = 0
    bms_cycle_count:     int   = 0
    bms_temperatures:    List[float] = field(default_factory=list)

    # Health events recorded during test
    health_events:       List[Dict] = field(default_factory=list)

    # ── Computed Properties ───────────────────────────────────────────────────

    @property
    def chemistry_config(self):
        return BATTERY_CHEMISTRIES.get(self.chemistry, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY])

    @property
    def storage_voltage(self):
        """Long-term storage voltage (not used for test end)"""
        return self.chemistry_config['storage_voltage']

    @property
    def discharge_end_voltage(self):
        """Test discharge endpoint - wait for BMS protection flag"""
        return self.chemistry_config.get('discharge_end_voltage', 3.00)

    @property
    def runtime_seconds(self):
        if self.start_time is None:
            return 0
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def runtime_str(self):
        s = int(self.runtime_seconds)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h > 0:
            return f"{h}h {m:02d}m {sec:02d}s"
        return f"{m}m {sec:02d}s"

    @property
    def capacity_percent(self):
        if self.rated_capacity_ah <= 0:
            return 0.0
        return (self.calculated_capacity_ah / self.rated_capacity_ah) * 100.0

    @property
    def time_data(self):
        return [s.timestamp for s in self.samples]

    @property
    def cell_data(self):
        if not self.samples:
            return []
        cell_count = len(self.samples[0].voltages)
        return [[s.voltages[i] for s in self.samples] for i in range(cell_count)]

    @property
    def cell_count(self):
        if not self.samples:
            return 0
        return len(self.samples[0].voltages)

    @property
    def latest_voltages(self):
        if not self.samples:
            return []
        return self.samples[-1].voltages

    @property
    def latest_current_ma(self):
        if not self.samples:
            return 0.0
        return self.samples[-1].current_ma


# ── Battery Test Engine ───────────────────────────────────────────────────────

class BatteryTestEngine:
    """
    Core test logic - shared between PyQt6 and Streamlit.
    Handles pre-check, data recording, capacity calculation, health checks.
    """

    def __init__(self):
        self.session: Optional[TestSession] = None

    # ── Session Management ────────────────────────────────────────────────────

    def new_session(self,
                    serial_number: str,
                    chemistry: str,
                    rated_capacity_ah: float,
                    pass_threshold_pct: float,
                    tech_initials: str = '',
                    mfg_date: str = '',
                    battery_age: str = '') -> TestSession:
        """Create a new test session"""
        self.session = TestSession(
            serial_number=serial_number,
            chemistry=chemistry,
            rated_capacity_ah=rated_capacity_ah,
            pass_threshold_pct=pass_threshold_pct,
            tech_initials=tech_initials,
            mfg_date=mfg_date,
            battery_age=battery_age,
            status=TestStatus.IDLE,
            result=TestResult.PENDING,
        )
        return self.session

    def start_test(self):
        """Mark test as started"""
        if self.session:
            self.session.status  = TestStatus.TESTING
            self.session.start_time = time.time()
            self.session.result  = TestResult.PENDING

    def stop_test(self, reason: str = 'Completed'):
        """Stop the test and finalize result"""
        if not self.session:
            return
        self.session.end_time = time.time()
        self.session.status   = TestStatus.COMPLETE
        self.session.stop_reason = reason

        # Auto pass/fail
        if self.session.result == TestResult.PENDING:
            if self.session.capacity_percent >= self.session.pass_threshold_pct:
                self.session.result = TestResult.PASS
            else:
                self.session.result = TestResult.FAIL

    def abort_test(self, reason: str = 'Error / Disconnected'):
        """Abort the test due to error or user closing app"""
        if self.session:
            self.session.end_time = time.time()
            self.session.status   = TestStatus.ABORTED
            self.session.stop_reason = reason

    def override_result(self, new_result: TestResult, reason: str):
        """User manually overrides pass/fail"""
        if self.session:
            self.session.result          = new_result
            self.session.override_reason = reason

    # ── Pre-Test Check ────────────────────────────────────────────────────────

    def run_pre_check(self, voltages: List[float]) -> PreCheckResult:
        """
        Run pre-test checks before allowing discharge to start.
        """
        result = PreCheckResult()

        if not voltages:
            result.messages.append("❌ No voltage data received from BMS")
            return result

        from core.config import NUMBER_OF_CELLS

        chem_key = self.session.chemistry if self.session else DEFAULT_CHEMISTRY
        chemistry = BATTERY_CHEMISTRIES.get(chem_key, BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY])
        min_start = chemistry.get('min_start_voltage', MIN_START_VOLTAGE)

        live      = [v for v in voltages if v >= 2.0]
        dead_idxs = [i + 1 for i, v in enumerate(voltages) if v < 2.0]

        result.cell_count = len(voltages)
        result.all_cells_found = (len(voltages) == NUMBER_OF_CELLS)
        if not result.all_cells_found:
            result.messages.append(f"❌ Expected {NUMBER_OF_CELLS} cells total, got {len(voltages)}")
        elif dead_idxs:
            result.messages.append(f"⚠ {len(dead_idxs)} dead cell(s) at position(s): {dead_idxs} — test allowed")
        else:
            result.messages.append(f"✅ All {NUMBER_OF_CELLS} cells detected")

        min_v = min(live) if live else 0.0
        max_v = max(live) if live else 0.0
        result.min_voltage   = min_v
        result.max_voltage   = max_v
        result.cells_charged = (min_v >= min_start)
        if result.cells_charged:
            result.messages.append(f"✅ Live cells charged (min: {min_v:.3f}V >= {min_start:.2f}V)")
        else:
            result.messages.append(f"❌ Live cell(s) below start threshold (min: {min_v:.3f}V < {min_start:.2f}V)")

        spread         = max_v - min_v if live else 0.0
        result.spread  = spread
        result.cells_balanced = (spread <= CELL_IMBALANCE_WARNING_V)
        if result.cells_balanced:
            result.messages.append(f"✅ Live cells balanced (spread: {spread:.3f}V)")
        else:
            result.messages.append(f"❌ Live cells unbalanced (spread: {spread:.3f}V > {CELL_IMBALANCE_WARNING_V}V)")

        return result

    # ── Data Recording ────────────────────────────────────────────────────────

    def record_voltage_sample(self, voltages: List[float], current_ma: float = 0.0):
        if not self.session or self.session.status != TestStatus.TESTING:
            return

        self.session.voltage_buffer.append(voltages.copy())
        self.session.current_buffer.append(current_ma)

        if len(self.session.voltage_buffer) > 5:
            self.session.voltage_buffer.pop(0)
        if len(self.session.current_buffer) > 5:
            self.session.current_buffer.pop(0)

        num_cells = len(voltages)
        avg_voltages = []
        for cell_idx in range(num_cells):
            cell_values = [buf[cell_idx] for buf in self.session.voltage_buffer]
            avg_voltages.append(sum(cell_values) / len(cell_values))

        avg_current = sum(self.session.current_buffer) / len(self.session.current_buffer)
        timestamp = time.time() - self.session.start_time

        sample = CellSample(timestamp=timestamp, voltages=avg_voltages, current_ma=avg_current)
        self.session.samples.append(sample)

        self._update_capacity(avg_current)
        self._check_health(avg_voltages, timestamp)

    def update_bms_info(self, info: dict):
        if not self.session:
            return
        if self.session.bms_initial_soc == 0:
            self.session.bms_initial_soc = info.get('rsoc_percent', 0)
        self.session.bms_cycle_count  = info.get('cycle_life', 0)
        self.session.bms_temperatures = info.get('temperatures_c', [])

    # ── Capacity Calculation ──────────────────────────────────────────────────

    def _update_capacity(self, current_ma: float):
        if not self.session:
            return

        now = time.time()

        if self.session.last_sample_time is not None:
            delta_hours = (now - self.session.last_sample_time) / 3600.0
            avg_current_a = (abs(self.session.last_current_ma) + abs(current_ma)) / 2.0 / 1000.0

            if current_ma < 0:   # Only when discharging
                self.session.calculated_capacity_ah += avg_current_a * delta_hours

        self.session.last_sample_time = now
        self.session.last_current_ma  = current_ma

    # ── Health Checks ─────────────────────────────────────────────────────────

    def _check_health(self, voltages: List[float], timestamp: float):
        if not self.session:
            return

        live = [v for v in voltages if v >= 2.0]
        if not live:
            return

        avg_v = sum(live) / len(live)
        chemistry = self.session.chemistry_config

        for i, v in enumerate(voltages):
            if v < 2.0:
                continue

            if abs(v - avg_v) >= CELL_IMBALANCE_ALERT_V:
                self.session.health_events.append({
                    'time': timestamp,
                    'type': 'IMBALANCE',
                    'cell': i + 1,
                    'voltage': v,
                    'avg': avg_v,
                    'message': f"Cell {i+1} is {abs(v-avg_v):.3f}V from average"
                })

            if v < chemistry['cell_fail_voltage']:
                self.session.health_events.append({
                    'time': timestamp,
                    'type': 'CRITICAL',
                    'cell': i + 1,
                    'voltage': v,
                    'message': f"Cell {i+1} below {chemistry['cell_fail_voltage']}V"
                })

    def get_current_health_status(self, voltages: List[float]) -> dict:
        if not voltages:
            return {'overall': 'UNKNOWN', 'issues': []}

        live = [v for v in voltages if v >= 2.0]
        dead = [(i + 1, v) for i, v in enumerate(voltages) if v < 2.0]

        if not live:
            return {'overall': 'UNKNOWN', 'issues': [{'type': 'DEAD_CELL', 'message': 'No live cells detected', 'severity': 'HIGH'}]}

        avg_v  = sum(live) / len(live)
        max_v  = max(live)
        min_v  = min(live)
        spread = max_v - min_v

        issues = []
        chemistry = BATTERY_CHEMISTRIES.get(
            self.session.chemistry if self.session else DEFAULT_CHEMISTRY,
            BATTERY_CHEMISTRIES[DEFAULT_CHEMISTRY]
        )

        if dead:
            cell_info = ', '.join([f"Cell {c}: {v:.3f}V" for c, v in dead])
            issues.append({'type': 'DEAD_CELL', 'message': f"Dead cell(s) detected — {cell_info}", 'severity': 'HIGH'})

        imbalanced = [i + 1 for i, v in enumerate(voltages) if v >= 2.0 and abs(v - avg_v) >= CELL_IMBALANCE_ALERT_V]
        if imbalanced:
            issues.append({'type': 'IMBALANCE', 'message': f"Cell(s) {imbalanced} are 0.5V+ from average", 'severity': 'HIGH'})

        if CELL_IMBALANCE_WARNING_V < spread < CELL_IMBALANCE_ALERT_V:
            issues.append({'type': 'SPREAD_WARNING', 'message': f"Voltage spread: {spread:.3f}V", 'severity': 'MEDIUM'})

        critical = [(i + 1, v) for i, v in enumerate(voltages) if 2.0 <= v < chemistry['cell_fail_voltage']]
        if critical:
            info = ', '.join([f"Cell {c}: {v:.3f}V" for c, v in critical])
            issues.append({'type': 'CRITICAL_VOLTAGE', 'message': f"Below {chemistry['cell_fail_voltage']}V: {info}", 'severity': 'HIGH'})

        overall = 'NORMAL' if not issues else ('ABNORMAL' if any(i['severity'] == 'HIGH' for i in issues) else 'WARNING')

        return {
            'overall': overall,
            'issues': issues,
            'avg_voltage': avg_v,
            'spread': spread,
            'min_voltage': min_v,
            'max_voltage': max_v,
        }
