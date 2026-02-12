"""
Battery Test System - Streamlit Web App
Each computer runs this locally - connects to its own BMS via USB.
Run with: streamlit run web/streamlit_app.py
"""

import time
import threading
import serial
import serial.tools.list_ports
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# Add parent dir to path so core/ is importable
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import (
    BATTERY_CHEMISTRIES, DEFAULT_CHEMISTRY, DEFAULT_RATED_CAPACITY_AH,
    DEFAULT_PASS_THRESHOLD_PCT, NUMBER_OF_CELLS, CELL_COLORS,
    AVAILABLE_BAUD_RATES, DEFAULT_BAUD_RATE, SERIAL_NUMBER_PREFIX,
    APP_NAME, APP_VERSION, MIN_START_VOLTAGE
)
from core.battery_test import BatteryTestEngine, TestStatus, TestResult
from core.bms_protocol import AWarriorBMS
from core.report_generator import (generate_csv, get_csv_filename,
                                    generate_pdf, get_pdf_filename)


# ── Page Config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🔋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Session State Init ────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        'engine':          None,
        'serial_conn':     None,
        'is_connected':    False,
        'is_testing':      False,
        'latest_voltages': [],
        'latest_current':  0.0,
        'latest_info':     {},
        'pre_check':       None,
        'bms':             AWarriorBMS(),
        'read_thread':     None,
        'thread_running':  False,
        'log_messages':    [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── BMS Serial (non-threaded for Streamlit compatibility) ─────────────────────

def _get_ports():
    return [f"{p.device} - {p.description}"
            for p in serial.tools.list_ports.comports()]


def _connect_bms(port_str: str, baud: int) -> bool:
    try:
        port = port_str.split(' - ')[0]
        conn = serial.Serial(
            port=port, baudrate=baud,
            bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE, timeout=1
        )
        conn.reset_input_buffer()
        st.session_state['serial_conn'] = conn
        st.session_state['is_connected'] = True
        _log(f"✓ Connected to {port} @ {baud} baud")
        return True
    except Exception as e:
        _log(f"✗ Connection failed: {e}")
        return False


def _disconnect_bms():
    conn = st.session_state.get('serial_conn')
    if conn and conn.is_open:
        conn.close()
    st.session_state['serial_conn']   = None
    st.session_state['is_connected']  = False
    st.session_state['thread_running'] = False
    _log("Disconnected")


def _read_frame(conn) -> bytes:
    response   = bytearray()
    start_time = time.time()
    while time.time() - start_time < 0.5:
        if conn.in_waiting > 0:
            response.extend(conn.read(1))
            if len(response) >= 7 and response[-1] == AWarriorBMS.STOP_BYTE:
                break
    return bytes(response) if response else b''


def _poll_bms():
    """Poll BMS once - call from background thread"""
    conn = st.session_state.get('serial_conn')
    bms  = st.session_state['bms']
    if not conn or not conn.is_open:
        return

    try:
        # Cell voltages
        conn.write(bms.get_cell_voltages_request())
        time.sleep(0.1)
        if conn.in_waiting:
            resp = _read_frame(conn)
            if resp and len(resp) >= 4 and resp[1] == AWarriorBMS.CMD_CELL_VOLTAGES:
                voltages = bms.parse_cell_voltages(resp)
                if voltages:
                    st.session_state['latest_voltages'] = voltages
                    if st.session_state.get('is_testing') and \
                            st.session_state.get('engine'):
                        current = st.session_state.get('latest_current', 0.0)
                        st.session_state['engine'].record_voltage_sample(
                            voltages, current
                        )

        time.sleep(0.2)

        # Basic info every 5 seconds
        if int(time.time()) % 5 == 0:
            conn.write(bms.get_basic_info_request())
            time.sleep(0.1)
            if conn.in_waiting:
                resp = _read_frame(conn)
                if resp and len(resp) >= 4 and resp[1] == AWarriorBMS.CMD_BASIC_INFO:
                    info = bms.parse_basic_info(resp)
                    if info:
                        st.session_state['latest_info']    = info
                        st.session_state['latest_current'] = info.get('current_ma', 0)
                        if st.session_state.get('engine'):
                            st.session_state['engine'].update_bms_info(info)

    except Exception as e:
        _log(f"Poll error: {e}")


def _log(msg: str):
    st.session_state['log_messages'].append(
        f"[{time.strftime('%H:%M:%S')}] {msg}"
    )
    if len(st.session_state['log_messages']) > 50:
        st.session_state['log_messages'] = \
            st.session_state['log_messages'][-50:]


# ── Chart Builder ─────────────────────────────────────────────────────────────

def _build_plotly_chart(session, storage_v: float):
    fig = go.Figure()

    if not session or not session.samples:
        fig.update_layout(
            title="Discharge Curves",
            xaxis_title="Time (s)",
            yaxis_title="Voltage (V)",
            height=400
        )
        return fig

    t         = session.time_data
    cell_data = session.cell_data

    for i, col in enumerate(cell_data):
        fig.add_trace(go.Scatter(
            x=t, y=col,
            name=f"Cell {i+1}",
            line=dict(color=CELL_COLORS[i % len(CELL_COLORS)], width=2),
            mode='lines'
        ))

    # Storage voltage line
    fig.add_hline(
        y=storage_v,
        line_dash="dash",
        line_color="#e67e22",
        annotation_text=f"Storage {storage_v}V",
        annotation_position="bottom right"
    )

    fig.update_layout(
        title="Discharge Curves",
        xaxis_title="Time (s)",
        yaxis_title="Voltage (V)",
        height=420,
        legend=dict(orientation="v", x=1.01, y=1),
        margin=dict(l=40, r=120, t=40, b=40),
        plot_bgcolor='white',
        paper_bgcolor='white'
    )
    fig.update_xaxes(showgrid=True, gridcolor='#eeeeee')
    fig.update_yaxes(showgrid=True, gridcolor='#eeeeee')

    return fig


# ── Main App ──────────────────────────────────────────────────────────────────

def main():
    # Title
    col_title, col_ver = st.columns([5, 1])
    with col_title:
        st.title(f"🔋 {APP_NAME}")
    with col_ver:
        st.caption(f"v{APP_VERSION}")

    st.divider()

    # ── Row 1: Connection + Test Setup ────────────────────────────────────────
    with st.container():
        c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1.5, 1, 1.5, 1.5])

        with c1:
            ports = _get_ports()
            selected_port = st.selectbox("COM Port", ports if ports else ['-- No ports --'])

        with c2:
            baud = st.selectbox("Baud Rate", AVAILABLE_BAUD_RATES,
                                index=AVAILABLE_BAUD_RATES.index(DEFAULT_BAUD_RATE))

        with c3:
            if not st.session_state['is_connected']:
                if st.button("🔌 Connect BMS", use_container_width=True, type="primary"):
                    _connect_bms(selected_port, int(baud))
                    st.rerun()
            else:
                st.success(f"Connected: {selected_port.split(' - ')[0]}")
                if st.button("❌ Disconnect", use_container_width=True):
                    _disconnect_bms()
                    st.rerun()

        with c4:
            chemistry_keys   = list(BATTERY_CHEMISTRIES.keys())
            chemistry_names  = [BATTERY_CHEMISTRIES[k]['name'] for k in chemistry_keys]
            selected_chem_idx = chemistry_keys.index(DEFAULT_CHEMISTRY)
            chem_name        = st.selectbox("Chemistry", chemistry_names,
                                            index=selected_chem_idx)
            chem_key         = chemistry_keys[chemistry_names.index(chem_name)]
            chem_config      = BATTERY_CHEMISTRIES[chem_key]

        with c5:
            rated_ah = st.number_input(
                "Rated Capacity (Ah)",
                min_value=1.0, max_value=1000.0,
                value=DEFAULT_RATED_CAPACITY_AH, step=1.0
            )

        with c6:
            threshold_pct = st.selectbox(
                "Pass Threshold",
                [80, 85, 90, 95, 100],
                index=[80, 85, 90, 95, 100].index(DEFAULT_PASS_THRESHOLD_PCT)
            )

    st.divider()

    # ── Poll BMS if connected ─────────────────────────────────────────────────
    if st.session_state['is_connected']:
        _poll_bms()

    # ── Row 2: Pre-Test Check + Serial Number ─────────────────────────────────
    voltages = st.session_state.get('latest_voltages', [])

    with st.container():
        col_sn, col_checks, col_actions = st.columns([2, 4, 2])

        with col_sn:
            serial_no = st.text_input(
                "Battery Serial Number",
                value=SERIAL_NUMBER_PREFIX,
                max_chars=20
            )

        with col_checks:
            st.write("**Pre-Test Check**")

            if voltages:
                live = [v for v in voltages if v >= 2.0]
                mn   = min(live) if live else 0
                mx   = max(live) if live else 0
                sprd = mx - mn

                all_cells  = len(live) == NUMBER_OF_CELLS
                charged    = mn >= MIN_START_VOLTAGE
                balanced   = sprd <= 0.05

                chk1, chk2, chk3 = st.columns(3)
                chk1.metric(
                    "Cells Detected",
                    f"{len(live)}/{NUMBER_OF_CELLS}",
                    delta="OK" if all_cells else "FAIL",
                    delta_color="normal" if all_cells else "inverse"
                )
                chk2.metric(
                    "Min Cell Voltage",
                    f"{mn:.3f}V",
                    delta="Charged" if charged else "Not charged",
                    delta_color="normal" if charged else "inverse"
                )
                chk3.metric(
                    "Cell Spread",
                    f"{sprd:.3f}V",
                    delta="Balanced" if balanced else "Unbalanced",
                    delta_color="normal" if balanced else "inverse"
                )
                pre_check_passed = all_cells and charged and balanced
            else:
                st.info("Connect BMS to run pre-test check")
                pre_check_passed = False

        with col_actions:
            st.write("**Test Control**")
            engine = st.session_state.get('engine')
            is_testing = (engine and engine.session and
                          engine.session.status == TestStatus.TESTING)

            if not is_testing:
                can_start = (pre_check_passed and
                             st.session_state['is_connected'] and
                             serial_no != SERIAL_NUMBER_PREFIX and
                             serial_no.strip() != '')
                if st.button("▶ START TEST", use_container_width=True,
                             type="primary", disabled=not can_start):
                    eng = BatteryTestEngine()
                    eng.new_session(serial_no, chem_key, rated_ah, threshold_pct)
                    eng.start_test()
                    st.session_state['engine']     = eng
                    st.session_state['is_testing'] = True
                    _log(f"▶ Test started: {serial_no}")
                    st.rerun()
            else:
                if st.button("■ STOP TEST", use_container_width=True, type="secondary"):
                    engine.stop_test()
                    st.session_state['is_testing'] = False
                    _log(f"■ Test stopped: {engine.session.result.value}")
                    st.rerun()

    st.divider()

    # ── Row 3: Chart ──────────────────────────────────────────────────────────
    engine = st.session_state.get('engine')
    fig    = _build_plotly_chart(
        engine.session if engine else None,
        chem_config['storage_voltage']
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Row 4: Health + Cell Voltages ─────────────────────────────────────────
    if voltages:
        col_health, col_cells = st.columns([2, 3])

        with col_health:
            st.subheader("Battery Health")
            if engine and engine.session:
                h = engine.get_current_health_status(voltages)
                overall = h['overall']
                if overall == 'NORMAL':
                    st.success("✅ NORMAL")
                elif overall == 'WARNING':
                    st.warning("⚠ WARNING")
                else:
                    st.error("⚠ ABNORMAL")

                for issue in h.get('issues', []):
                    sev = issue['severity']
                    if sev == 'HIGH':
                        st.error(issue['message'])
                    else:
                        st.warning(issue['message'])

                # Target
                if engine.session.status == TestStatus.TESTING:
                    avg = h.get('avg_voltage', 0)
                    sv  = engine.session.storage_voltage
                    st.info(f"Avg: {avg:.3f}V → {avg-sv:.3f}V above {sv}V target")
                elif engine.session.status == TestStatus.COMPLETE:
                    st.success("✅ Discharge complete!")

        with col_cells:
            st.subheader("Cell Voltages")
            live = [v for v in voltages if v >= 2.0]
            avg  = sum(live) / len(live) if live else 0

            cols_per_row = 7
            rows = [voltages[i:i+cols_per_row]
                    for i in range(0, len(voltages), cols_per_row)]
            for row_idx, row_vs in enumerate(rows):
                row_cols = st.columns(len(row_vs))
                for col_idx, v in enumerate(row_vs):
                    cell_num = row_idx * cols_per_row + col_idx + 1
                    with row_cols[col_idx]:
                        if v < 1.0:
                            st.error(f"C{cell_num}\n{v:.3f}V\nDEAD")
                        elif v < 2.5:
                            st.error(f"C{cell_num}\n{v:.3f}V\nCRIT")
                        elif v < chem_config['cell_fail_voltage']:
                            st.warning(f"C{cell_num}\n{v:.3f}V\nLOW")
                        else:
                            st.metric(f"Cell {cell_num}", f"{v:.3f}V")

    st.divider()

    # ── Row 5: Live Stats + Capacity Result ───────────────────────────────────
    if engine and engine.session:
        sess = engine.session
        col_stats, col_result = st.columns([3, 2])

        with col_stats:
            st.subheader("Live Statistics")
            live = [v for v in voltages if v >= 2.0] if voltages else []
            info = st.session_state.get('latest_info', {})

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Avg Voltage",
                      f"{sum(live)/len(live):.3f}V" if live else "--")
            s2.metric("Spread",
                      f"{max(live)-min(live):.3f}V" if live else "--")
            s3.metric("Current",
                      f"{info.get('current_ma',0)} mA")
            s4.metric("Runtime", sess.runtime_str)

            s5, s6, s7, s8 = st.columns(4)
            s5.metric("SoC (BMS)", f"{info.get('rsoc_percent',0)}%")
            s6.metric("BMS Capacity",
                      f"{info.get('residual_capacity_mah',0)} mAh")
            s7.metric("Storage Target",
                      f"{sess.storage_voltage:.2f}V")
            s8.metric("Cycle Count",
                      str(sess.bms_cycle_count))

        with col_result:
            st.subheader("Capacity Result")

            ah  = sess.calculated_capacity_ah
            pct = sess.capacity_percent

            st.metric("Measured Capacity",
                      f"{ah:.4f} Ah",
                      delta=f"{ah*1000:.1f} mAh")
            st.metric("Capacity %",
                      f"{pct:.1f}%",
                      delta=f"vs {sess.pass_threshold_pct:.0f}% threshold")

            # Result display
            if sess.status in (TestStatus.COMPLETE, TestStatus.ABORTED):
                if sess.result == TestResult.PASS:
                    st.success(f"✅ PASS  ({pct:.1f}%)")
                elif sess.result == TestResult.FAIL:
                    st.error(f"❌ FAIL  ({pct:.1f}%)")
                else:
                    st.warning(f"⚠ {sess.result.value}")

                # Override
                st.write("**Override Result:**")
                override = st.selectbox(
                    "Override",
                    ['No override', 'Mark as PASS', 'Mark as FAIL'],
                    label_visibility='collapsed'
                )
                reason = st.text_input("Override reason")
                if override != 'No override' and st.button("Apply Override"):
                    new_res = TestResult.PASS if 'PASS' in override else TestResult.FAIL
                    engine.override_result(new_res, reason)
                    st.rerun()

                # Export
                st.write("**Export Report:**")
                exp1, exp2 = st.columns(2)
                with exp1:
                    csv_data = generate_csv(sess)
                    st.download_button(
                        "📥 Download CSV",
                        data=csv_data,
                        file_name=get_csv_filename(sess),
                        mime='text/csv',
                        use_container_width=True
                    )
                with exp2:
                    pdf_data = generate_pdf(sess)
                    st.download_button(
                        "📄 Download PDF",
                        data=pdf_data,
                        file_name=get_pdf_filename(sess),
                        mime='application/pdf',
                        use_container_width=True
                    )

    # ── Auto-refresh while testing ────────────────────────────────────────────
    if st.session_state.get('is_connected') or st.session_state.get('is_testing'):
        time.sleep(1)
        st.rerun()


if __name__ == '__main__':
    main()
