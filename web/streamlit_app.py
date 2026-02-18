"""
Battery Test System - Streamlit Web App
Each computer runs this locally - connects to its own BMS via USB.
Run with: streamlit run web/streamlit_app.py
"""

import time
import serial
import serial.tools.list_ports
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Add parent dir to path so core/ is importable
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import (
    BATTERY_CHEMISTRIES, DEFAULT_CHEMISTRY, DEFAULT_RATED_CAPACITY_AH,
    DEFAULT_PASS_THRESHOLD_PCT, NUMBER_OF_CELLS, CELL_COLORS,
    AVAILABLE_BAUD_RATES, DEFAULT_BAUD_RATE, SERIAL_NUMBER_PREFIX,
    APP_NAME, APP_VERSION, LOGO_PATH
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
        'log_messages':    [],
        'poll_counter':    0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── BMS Serial Communication ──────────────────────────────────────────────────

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
        return True
    except Exception:
        return False


def _disconnect_bms():
    conn = st.session_state.get('serial_conn')
    if conn and conn.is_open:
        conn.close()
    st.session_state['serial_conn']   = None
    st.session_state['is_connected']  = False
    st.session_state['is_testing']    = False


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
    """Poll BMS - reads voltage and current"""
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
                    if st.session_state.get('is_testing') and st.session_state.get('engine'):
                        current = st.session_state.get('latest_current', 0.0)
                        st.session_state['engine'].record_voltage_sample(voltages, current)

        time.sleep(0.2)

        # Basic info (every 2nd poll)
        st.session_state['poll_counter'] += 1
        if st.session_state['poll_counter'] % 2 == 0:
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

                        # Check BMS protection
                        if st.session_state.get('is_testing'):
                            prot = info.get('protection_status', 0)
                            if (prot & 0x01) != 0:
                                st.session_state['engine'].stop_test()
                                st.session_state['is_testing'] = False

    except Exception:
        pass


# ── Chart Builder ─────────────────────────────────────────────────────────────

def _build_combined_chart(session, discharge_end_v: float):
    """Single chart with dual Y-axes: voltage + current"""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if not session or not session.samples:
        fig.update_layout(
            title="Discharge Curves: Cell Voltages + Current",
            xaxis_title="Time (s)",
            yaxis_title="Voltage (V)",
            height=450
        )
        return fig

    t          = session.time_data
    cell_data  = session.cell_data

    # Voltage traces
    for i, col in enumerate(cell_data):
        fig.add_trace(
            go.Scatter(
                x=t, y=col,
                name=f"Cell {i+1}",
                line=dict(color=CELL_COLORS[i % len(CELL_COLORS)], width=2),
                mode='lines'
            ),
            secondary_y=False
        )

    # Discharge end line
    fig.add_hline(
        y=discharge_end_v,
        line_dash="dash",
        line_color="#e67e22",
        annotation_text=f"Min {discharge_end_v}V",
        annotation_position="bottom right",
        secondary_y=False
    )

    # Current trace
    current_data = [s.current_ma / 1000.0 for s in session.samples]
    fig.add_trace(
        go.Scatter(
            x=t, y=current_data,
            name="Current (A)",
            line=dict(color='#2c3e50', width=3),
            mode='lines'
        ),
        secondary_y=True
    )

    fig.update_layout(
        title="Discharge Curves: Cell Voltages + Current",
        xaxis_title="Time (s)",
        height=450,
        legend=dict(orientation="v", x=1.05, y=1),
        margin=dict(l=40, r=150, t=40, b=40),
        plot_bgcolor='white'
    )

    fig.update_xaxes(showgrid=True, gridcolor='#eee')
    fig.update_yaxes(title_text="Voltage (V)", showgrid=True, gridcolor='#eee', secondary_y=False)
    fig.update_yaxes(title_text="Current (A)", showgrid=True, gridcolor='#eee', secondary_y=True, range=[-60, 0])

    return fig


# ── Main App ──────────────────────────────────────────────────────────────────

def main():
    # Logo
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=200)

    # Title
    col_t, col_v = st.columns([5, 1])
    with col_t:
        st.title(f"🔋 {APP_NAME}")
    with col_v:
        st.caption(f"v{APP_VERSION}")
    st.divider()

    # Connection
    c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1.5, 1, 1.5, 1.5])
    with c1:
        ports = _get_ports()
        port = st.selectbox("COM Port", ports if ports else ['No ports'])
    with c2:
        baud = st.selectbox("Baud", AVAILABLE_BAUD_RATES,
                            index=AVAILABLE_BAUD_RATES.index(DEFAULT_BAUD_RATE))
    with c3:
        if not st.session_state['is_connected']:
            if st.button("🔌 Connect", use_container_width=True, type="primary"):
                if _connect_bms(port, int(baud)):
                    st.rerun()
        else:
            st.success(f"Connected")
            if st.button("❌ Disconnect", use_container_width=True):
                _disconnect_bms()
                st.rerun()
    with c4:
        chem_keys = list(BATTERY_CHEMISTRIES.keys())
        chem_names = [BATTERY_CHEMISTRIES[k]['name'] for k in chem_keys]
        chem_name = st.selectbox("Chemistry", chem_names, index=chem_keys.index(DEFAULT_CHEMISTRY))
        chem_key = chem_keys[chem_names.index(chem_name)]
        chem = BATTERY_CHEMISTRIES[chem_key]
    with c5:
        rated_ah = st.number_input("Rated Ah", 1.0, 1000.0,
                                   chem.get('rated_capacity_ah', 62.0), 1.0)
    with c6:
        threshold = st.selectbox("Pass >=", [80,85,90,95,100], index=4)

    st.divider()

    # Poll BMS
    if st.session_state['is_connected']:
        _poll_bms()

    voltages = st.session_state.get('latest_voltages', [])

    # Pre-check + Start
    col_sn, col_check, col_act = st.columns([2, 4, 2])
    with col_sn:
        sn = st.text_input("Battery Serial", SERIAL_NUMBER_PREFIX, max_chars=20)
    with col_check:
        st.write("**Pre-Test Check**")
        if voltages:
            live = [v for v in voltages if v >= 2.0]
            dead_cnt = len(voltages) - len(live)
            mn, mx = (min(live), max(live)) if live else (0, 0)
            sprd = mx - mn
            min_st = chem.get('min_start_voltage', 3.5)

            ok1 = len(voltages) == NUMBER_OF_CELLS
            ok2 = mn >= min_st
            ok3 = sprd <= 0.05

            c1, c2, c3 = st.columns(3)
            c1.metric("Cells", f"{len(live)}/{NUMBER_OF_CELLS}",
                      delta=f"{'✅' if ok1 else '❌'} {dead_cnt} dead" if dead_cnt else "✅")
            c2.metric("Min V", f"{mn:.3f}V",
                      delta=f"{'✅' if ok2 else '❌'} need ≥{min_st:.2f}V")
            c3.metric("Spread", f"{sprd:.3f}V",
                      delta="✅" if ok3 else "❌")
            pre_ok = ok1 and ok2 and ok3
        else:
            st.info("Connect BMS")
            pre_ok = False

    with col_act:
        st.write("**Test Control**")
        eng = st.session_state.get('engine')
        testing = st.session_state.get('is_testing')
        if not testing:
            can_start = pre_ok and st.session_state['is_connected'] and sn != SERIAL_NUMBER_PREFIX
            if st.button("▶ START", use_container_width=True, type="primary", disabled=not can_start):
                e = BatteryTestEngine()
                e.new_session(sn, chem_key, rated_ah, threshold)
                e.start_test()
                st.session_state['engine'] = e
                st.session_state['is_testing'] = True
                st.rerun()
        else:
            if st.button("■ STOP", use_container_width=True):
                eng.stop_test()
                st.session_state['is_testing'] = False
                st.rerun()

    st.divider()

    # Chart
    fig = _build_combined_chart(
        eng.session if eng else None,
        chem.get('discharge_end_voltage', 3.0)
    )
    st.plotly_chart(fig, use_container_width=True)

    # Health + Cells
    if voltages:
        col_h, col_c = st.columns([2, 3])
        with col_h:
            st.subheader("Health")
            if eng and eng.session:
                h = eng.get_current_health_status(voltages)
                ov = h['overall']
                if ov == 'NORMAL':
                    st.success("✅ NORMAL")
                elif ov == 'WARNING':
                    st.warning("⚠ WARNING")
                else:
                    st.error("⚠ ABNORMAL")
                for iss in h.get('issues', []):
                    if iss['severity'] == 'HIGH':
                        st.error(iss['message'])
                    else:
                        st.warning(iss['message'])
        with col_c:
            st.subheader("Cells")
            cols_per = 7
            rows = [voltages[i:i+cols_per] for i in range(0, len(voltages), cols_per)]
            for ridx, rvs in enumerate(rows):
                rcs = st.columns(len(rvs))
                for cidx, v in enumerate(rvs):
                    cnum = ridx * cols_per + cidx + 1
                    with rcs[cidx]:
                        if v < 1.0:
                            st.error(f"C{cnum}\n{v:.3f}V\nDEAD")
                        elif v < 2.5:
                            st.error(f"C{cnum}\n{v:.3f}V")
                        else:
                            st.metric(f"C{cnum}", f"{v:.3f}V")

    st.divider()

    # Stats + Result
    if eng and eng.session:
        sess = eng.session
        col_st, col_res = st.columns([3, 2])
        with col_st:
            st.subheader("Live Stats")
            live = [v for v in voltages if v >= 2.0] if voltages else []
            info = st.session_state.get('latest_info', {})
            curr = info.get('current_ma', 0)

            s1,s2,s3,s4 = st.columns(4)
            s1.metric("Avg V", f"{sum(live)/len(live):.3f}V" if live else "--")
            s2.metric("Spread", f"{max(live)-min(live):.3f}V" if live else "--")
            s3.metric("Current", f"{curr/1000:.2f} A")
            s4.metric("Runtime", sess.runtime_str)

            s5,s6,s7,s8 = st.columns(4)
            s5.metric("Meas Cap", f"{sess.calculated_capacity_ah:.4f} Ah")
            s6.metric("Cap %", f"{sess.capacity_percent:.1f}%")
            s7.metric("SoC", f"{info.get('rsoc_percent',0)}%")
            s8.metric("BMS Cap", f"{info.get('residual_capacity_mah',0)} mAh")

        with col_res:
            st.subheader("Result")
            ah = sess.calculated_capacity_ah
            pct = sess.capacity_percent
            st.metric("Measured", f"{ah:.4f} Ah", delta=f"{ah*1000:.1f} mAh")
            st.metric("Capacity %", f"{pct:.1f}%")

            if sess.status in (TestStatus.COMPLETE, TestStatus.ABORTED):
                if sess.result == TestResult.PASS:
                    st.success(f"✅ PASS ({pct:.1f}%)")
                elif sess.result == TestResult.FAIL:
                    st.error(f"❌ FAIL ({pct:.1f}%)")

                # Export
                st.write("**Export:**")
                e1, e2 = st.columns(2)
                with e1:
                    st.download_button("📥 CSV", generate_csv(sess),
                                       get_csv_filename(sess), "text/csv",
                                       use_container_width=True)
                with e2:
                    st.download_button("📄 PDF", generate_pdf(sess),
                                       get_pdf_filename(sess), "application/pdf",
                                       use_container_width=True)

    # Auto-refresh
    if st.session_state.get('is_connected') or st.session_state.get('is_testing'):
        time.sleep(1)
        st.rerun()


if __name__ == '__main__':
    main()