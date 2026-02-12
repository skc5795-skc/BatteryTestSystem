# Battery Test System

Production battery discharge test system for 14-cell NMC prismatic packs.

## Project Structure

```
BatteryTestSystem/
├── main.py                      ← Entry point (desktop or web)
├── requirements.txt
│
├── core/                        ← Shared logic (used by both apps)
│   ├── config.py                  Battery chemistries, thresholds, settings
│   ├── bms_protocol.py            A-Warrior BMS RS485 protocol handler
│   ├── battery_test.py            Test engine, pass/fail, capacity calculation
│   └── report_generator.py        CSV and PDF report generation
│
├── desktop/                     ← PyQt6 desktop application
│   ├── main.py
│   ├── serial_thread.py           Background BMS communication thread
│   └── battery_monitor_ui.py      Full desktop UI
│
└── web/                         ← Streamlit web application
    └── streamlit_app.py           Browser-based UI (same logic as desktop)
```

## Installation

```bash
pip install -r requirements.txt
```

## Running

### Desktop App (PyQt6)
```bash
python main.py
```

### Web App (Streamlit)
```bash
python main.py --web
# Then open http://localhost:8501 in any browser on this computer
```

Or directly:
```bash
streamlit run web/streamlit_app.py
```

## Test Workflow

1. **Connect BMS** — Select COM port, click Connect
2. **Pre-Test Check** — Automatic when BMS is connected
   - All 14 cells detected
   - All cells charged (>3.80V)
   - Cells balanced (<50mV spread)
3. **Enter Serial Number** — Pre-filled with `B14S`, add the rest
4. **Configure Test** — Chemistry, rated capacity, pass threshold
5. **Start Test** — Button enabled only when pre-check passes
6. **Discharge runs** — Graphs update every second, health monitored
7. **Auto-stop** — When average cell voltage hits storage voltage
8. **Export Report** — CSV (raw data) or PDF (summary + graph + per-cell table)

## Battery Chemistries Supported

| Chemistry     | Storage V | Full Charge V | Fail V |
|---------------|-----------|---------------|--------|
| NMC Prismatic | 3.60V     | 4.15V         | 3.00V  |
| LiPo          | 3.80V     | 4.15V         | 3.00V  |
| LiFePO4       | 3.30V     | 3.55V         | 2.80V  |
| NCA           | 3.67V     | 4.10V         | 3.00V  |

## Pass/Fail Criteria

- **Capacity**: Measured Ah ÷ Rated Ah × 100% ≥ Pass threshold (default 95%)
- **User override**: Available via dropdown with reason field
- Reports named: `B14S001_20240212_143022_PASS.pdf`

## BMS Protocol

A-Warrior General Protocol V4 — RS485/UART at 9600 baud  
Commands used: `0x03` (basic info), `0x04` (cell voltages)

## Serial Number Format

`B14S` + 3 digits, e.g. `B14S001`, `B14S002`, ...
