"""
Report Generator
Generates CSV and PDF test reports from a TestSession.
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from xml.sax.saxutils import escape

from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from core.battery_test import TestResult, TestSession, TestStatus
from core.config import (
    APP_NAME,
    APP_VERSION,
    CELL_COLORS,
    COPPERSTONE_GREEN,
    COPPERSTONE_TEAL,
    LOGO_PATH,
)

COPPERSTONE_ORANGE = "#F4950D"


def _attr(session: TestSession, name: str, default=None):
    """Read optional fields without breaking older TestSession objects."""
    try:
        value = getattr(session, name, default)
    except Exception:
        return default
    return default if value is None else value


def _final_cell_values(session: TestSession) -> list[float]:
    values = _attr(session, "final_cell_voltages", None)
    if values is None:
        samples = _attr(session, "samples", []) or []
        values = samples[-1].voltages if samples else []
    return [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and value >= 2.0
    ]


def _final_cell_stats(session: TestSession) -> tuple[float, float, float, float]:
    values = _final_cell_values(session)
    if not values:
        return 0.0, 0.0, 0.0, 0.0

    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    std_v = variance ** 0.5
    spread_v = max(values) - min(values)
    return average, std_v, std_v * 1000.0, spread_v


def generate_csv(session: TestSession) -> str:
    output = io.StringIO()
    writer = csv.writer(output)

    average_v, std_v, std_mv, spread_v = _final_cell_stats(session)

    writer.writerow(["Battery Test Report"])
    writer.writerow(["Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow(["Battery Serial", _attr(session, "serial_number", "")])
    writer.writerow(["Cell Batch #", _attr(session, "cell_batch", "")])
    writer.writerow(["Tech Initials", _attr(session, "tech_initials", "")])
    writer.writerow(["MFG Date", _attr(session, "mfg_date", "")])
    writer.writerow(["Battery Age", _attr(session, "battery_age", "")])
    writer.writerow(["Chemistry", _attr(session, "chemistry", "")])
    writer.writerow(["Rated Capacity (Ah)", f'{float(_attr(session, "rated_capacity_ah", 0.0)):.1f}'])
    writer.writerow(["Measured Capacity (Ah)", f'{float(_attr(session, "calculated_capacity_ah", 0.0)):.4f}'])
    writer.writerow(["Measured Capacity (mAh)", f'{float(_attr(session, "calculated_capacity_ah", 0.0)) * 1000:.1f}'])
    writer.writerow(["Capacity (%)", f'{float(_attr(session, "capacity_percent", 0.0)):.1f}'])
    writer.writerow(["Final Cell Average (V)", f"{average_v:.4f}"])
    writer.writerow(["Final Cell Standard Deviation (V)", f"{std_v:.6f}"])
    writer.writerow(["Final Cell Standard Deviation (mV)", f"{std_mv:.2f}"])
    writer.writerow(["Final Cell Spread (V)", f"{spread_v:.4f}"])
    writer.writerow(["Pass Threshold (%)", f'{float(_attr(session, "pass_threshold_pct", 0.0)):.0f}'])
    writer.writerow(["Test Stopped By", _attr(session, "stop_reason", "")])

    result = _attr(session, "result", None)
    writer.writerow(["Result", getattr(result, "value", str(result or ""))])

    override_reason = _attr(session, "override_reason", "")
    if override_reason:
        writer.writerow(["Override Reason", override_reason])

    writer.writerow(["Runtime", _attr(session, "runtime_str", "")])
    writer.writerow(["Storage Voltage (V)", f'{float(_attr(session, "storage_voltage", 0.0)):.2f}'])
    writer.writerow(["Discharge End Voltage (V)", f'{float(_attr(session, "discharge_end_voltage", 0.0)):.2f}'])
    writer.writerow(["BMS Cycle Count", _attr(session, "bms_cycle_count", 0)])
    writer.writerow([])

    health_events = _attr(session, "health_events", []) or []
    if health_events:
        writer.writerow(["Health Events"])
        writer.writerow(["Time (s)", "Type", "Cell", "Voltage (V)", "Message"])
        for event in health_events:
            voltage = event.get("voltage")
            writer.writerow([
                f'{float(event.get("time", 0.0)):.1f}',
                event.get("type", ""),
                event.get("cell", ""),
                f"{float(voltage):.3f}" if isinstance(voltage, (int, float)) else "",
                event.get("message", ""),
            ])
        writer.writerow([])

    samples = _attr(session, "samples", []) or []
    if samples:
        cell_count = len(samples[0].voltages)
        headers = ["Time (s)", "Current (mA)"] + [
            f"Cell {index + 1} (V)" for index in range(cell_count)
        ]
        writer.writerow(headers)

        for sample in samples:
            writer.writerow([
                f"{float(sample.timestamp):.1f}",
                f"{float(sample.current_ma):.0f}",
                *[f"{float(value):.4f}" for value in sample.voltages],
            ])

    return output.getvalue()


def get_csv_filename(session: TestSession) -> str:
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = _attr(session, "result", None)
    result_text = getattr(result, "value", str(result or "Pending"))
    serial = _attr(session, "serial_number", "Battery") or "Battery"
    return f"{serial}_{date_str}_{result_text}.csv"


def _result_colours(session: TestSession):
    result = _attr(session, "result", None)
    if result == TestResult.PASS:
        return colors.HexColor(COPPERSTONE_GREEN), colors.HexColor("#eafaf1")
    if result == TestResult.FAIL:
        return colors.HexColor("#e74c3c"), colors.HexColor("#fdedec")
    return colors.HexColor("#f39c12"), colors.HexColor("#fef9e7")


def _result_text(session: TestSession) -> str:
    result = _attr(session, "result", None)
    return getattr(result, "value", str(result or "Pending"))


def _section_table(data: list[list[str]], widths: list[float], header: bool = False) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]
    if header:
        commands.extend([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COPPERSTONE_TEAL)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f9f8")]),
        ])
    table.setStyle(TableStyle(commands))
    return table


def generate_pdf(session: TestSession) -> bytes:
    buffer = io.BytesIO()

    portrait_page_size = letter
    landscape_page_size = landscape(letter)

    left_margin = 0.75 * inch
    right_margin = 0.75 * inch
    top_margin = 0.65 * inch
    bottom_margin = 0.65 * inch

    # Keep the report information pages in portrait, but use a dedicated
    # landscape page for the discharge graph.
    doc = BaseDocTemplate(
        buffer,
        pagesize=portrait_page_size,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        title="Battery Test Report",
        author=APP_NAME,
    )

    portrait_frame = Frame(
        left_margin,
        bottom_margin,
        portrait_page_size[0] - left_margin - right_margin,
        portrait_page_size[1] - top_margin - bottom_margin,
        id="portrait_frame",
    )
    landscape_frame = Frame(
        left_margin,
        bottom_margin,
        landscape_page_size[0] - left_margin - right_margin,
        landscape_page_size[1] - top_margin - bottom_margin,
        id="landscape_frame",
    )

    doc.addPageTemplates([
        PageTemplate(
            id="Portrait",
            pagesize=portrait_page_size,
            frames=[portrait_frame],
        ),
        PageTemplate(
            id="Landscape",
            pagesize=landscape_page_size,
            frames=[landscape_frame],
        ),
    ])

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontSize=22,
        textColor=colors.HexColor(COPPERSTONE_TEAL),
        spaceAfter=6,
    )
    heading_style = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontSize=14,
        textColor=colors.HexColor(COPPERSTONE_TEAL),
        spaceBefore=12,
        spaceAfter=6,
    )
    normal_style = styles["Normal"]
    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.grey,
    )

    story = []

    # App-style report header: teal banner, centred Copperstone logo, product
    # name/version at the lower right, and a thin orange divider underneath.
    logo_flowable = ""
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        try:
            logo_flowable = Image(
                LOGO_PATH,
                width=3.1 * inch,
                height=0.72 * inch,
                kind="proportional",
            )
        except Exception as exc:
            print(f"Could not add logo to PDF header: {exc}")
            logo_flowable = ""

    header_title_style = ParagraphStyle(
        "HeaderTitle",
        parent=normal_style,
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.white,
        alignment=2,
    )
    header_table = Table(
        [[
            "",
            logo_flowable,
            Paragraph(
                f"{escape(APP_NAME)} v{escape(APP_VERSION)}",
                header_title_style,
            ),
        ]],
        colWidths=[1.65 * inch, 3.70 * inch, 1.65 * inch],
        rowHeights=[0.86 * inch],
    )
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COPPERSTONE_TEAL)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0, colors.HexColor(COPPERSTONE_TEAL)),
        # Thin orange divider attached directly to the teal header.
        ("LINEBELOW", (0, 0), (-1, -1), 3, colors.HexColor(COPPERSTONE_ORANGE)),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Battery Test Report", title_style))
    story.append(Spacer(1, 0.08 * inch))

    result_color, result_bg = _result_colours(session)
    result_style = ParagraphStyle(
        "Result",
        parent=normal_style,
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=20,
        textColor=result_color,
        alignment=1,
        spaceBefore=0,
        spaceAfter=0,
    )
    result_table = Table(
        [[Paragraph(
            f"TEST RESULT: {escape(_result_text(session))}",
            result_style,
        )]],
        colWidths=[7 * inch],
        rowHeights=[0.62 * inch],
    )
    result_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), result_bg),
        ("BOX", (0, 0), (-1, -1), 1.5, result_color),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([result_table, Spacer(1, 0.12 * inch)])

    story.append(Paragraph("Battery Information", heading_style))
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    average_v, std_v, std_mv, spread_v = _final_cell_stats(session)

    info_value_style = ParagraphStyle(
        "InfoValue",
        parent=normal_style,
        fontSize=8.5,
        leading=10,
    )

    info_data = [
        ["Battery Serial", str(_attr(session, "serial_number", "")), "Test Date", date_str],
        ["Chemistry", str(_attr(session, "chemistry", "")), "MFG Date", str(_attr(session, "mfg_date", ""))],
        ["Rated Capacity", f'{float(_attr(session, "rated_capacity_ah", 0.0)):.1f} Ah', "Battery Age", str(_attr(session, "battery_age", ""))],
        ["Storage Voltage", f'{float(_attr(session, "storage_voltage", 0.0)):.2f} V', "Runtime", str(_attr(session, "runtime_str", ""))],
        ["Pass Threshold", f'>= {float(_attr(session, "pass_threshold_pct", 0.0)):.0f}%', "Cycle Count (BMS)", str(_attr(session, "bms_cycle_count", 0))],
        [
            "Cell Batch #",
            str(_attr(session, "cell_batch", "") or "-"),
            "Test Stopped By",
            Paragraph(escape(str(_attr(session, "stop_reason", ""))), info_value_style),
        ],
        ["Final Cell Std Dev", f"{std_mv:.2f} mV", "Final Cell Spread", f"{spread_v:.3f} V"],
        ["Tech Initials", str(_attr(session, "tech_initials", "")), "QC By", "____________________"],
    ]

    info_table = Table(info_data, colWidths=[1.5 * inch, 2 * inch, 1.5 * inch, 2 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(COPPERSTONE_TEAL)),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor(COPPERSTONE_TEAL)),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([info_table, Spacer(1, 0.12 * inch)])

    story.append(Paragraph("Capacity Results", heading_style))
    cap_pct = float(_attr(session, "capacity_percent", 0.0))
    threshold = float(_attr(session, "pass_threshold_pct", 0.0))
    status = "PASS" if cap_pct >= threshold else "FAIL"
    cap_data = [
        ["Metric", "Value", "Status"],
        ["Rated Capacity", f'{float(_attr(session, "rated_capacity_ah", 0.0)):.2f} Ah', "-"],
        ["Measured Capacity", f'{float(_attr(session, "calculated_capacity_ah", 0.0)):.4f} Ah', "-"],
        ["Capacity Percentage", f"{cap_pct:.1f}%", status],
        ["Pass Threshold", f">= {threshold:.0f}%", "-"],
        ["Final Cell Average", f"{average_v:.4f} V", "-"],
        ["Final Cell Std Dev", f"{std_mv:.2f} mV", "-"],
    ]
    cap_table = _section_table(cap_data, [2.2 * inch, 3 * inch, 1.8 * inch], header=True)
    status_color = colors.HexColor(COPPERSTONE_GREEN if status == "PASS" else "#e74c3c")
    cap_table.setStyle(TableStyle([
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("TEXTCOLOR", (2, 3), (2, 3), status_color),
        ("FONTNAME", (2, 3), (2, 3), "Helvetica-Bold"),
    ]))
    story.append(cap_table)

    override_reason = _attr(session, "override_reason", "")
    if override_reason:
        story.extend([
            Spacer(1, 0.1 * inch),
            Paragraph(f"<b>Override Reason:</b> {escape(str(override_reason))}", normal_style),
        ])

    temperatures = _attr(session, "bms_temperatures", []) or []
    if temperatures:
        temp_text = ", ".join(f"{float(value):.1f} C" for value in temperatures)
        story.extend([
            Spacer(1, 0.1 * inch),
            Paragraph(f"<b>BMS Temperatures:</b> {escape(temp_text)}", normal_style),
        ])

    health_events = _attr(session, "health_events", []) or []
    if health_events:
        story.extend([Spacer(1, 0.12 * inch), Paragraph("Health Events During Test", heading_style)])
        event_data = [["Time (s)", "Type", "Cell", "Voltage", "Description"]]
        for event in health_events[:20]:
            voltage = event.get("voltage")
            event_data.append([
                f'{float(event.get("time", 0.0)):.1f}',
                str(event.get("type", "")),
                str(event.get("cell", "-")),
                f"{float(voltage):.3f} V" if isinstance(voltage, (int, float)) else "-",
                str(event.get("message", "")),
            ])
        story.append(_section_table(
            event_data,
            [0.7 * inch, 1 * inch, 0.5 * inch, 0.8 * inch, 4 * inch],
            header=True,
        ))

    # Switch only the discharge-curve page to landscape orientation.
    story.append(NextPageTemplate("Landscape"))
    story.append(PageBreak())
    story.append(Paragraph("Discharge Curves", heading_style))
    story.append(Spacer(1, 0.08 * inch))

    samples = _attr(session, "samples", []) or []
    if len(samples) >= 2:
        story.append(_build_discharge_chart(session))
    else:
        story.append(Paragraph("Not enough data to generate chart.", normal_style))

    # Return to portrait for the remaining report pages.
    story.append(NextPageTemplate("Portrait"))
    story.append(PageBreak())
    story.append(Paragraph("Per-Cell Voltage Summary", heading_style))

    cell_data = _attr(session, "cell_data", []) or []
    if cell_data:
        per_cell_data = [["Cell", "Start (V)", "End (V)", "Min (V)", "Max (V)", "Drop (V)"]]
        for index, column in enumerate(cell_data):
            if not column:
                continue
            start = float(column[0])
            end = float(column[-1])
            per_cell_data.append([
                f"Cell {index + 1}",
                f"{start:.3f}",
                f"{end:.3f}",
                f"{min(column):.3f}",
                f"{max(column):.3f}",
                f"{start - end:.3f}",
            ])
        story.append(_section_table(per_cell_data, [1.1 * inch] * 6, header=True))
    else:
        story.append(Paragraph("No per-cell data available.", normal_style))

    story.extend([
        Spacer(1, 0.3 * inch),
        HRFlowable(width="100%", thickness=0.5, color=colors.grey),
        Spacer(1, 0.05 * inch),
        Paragraph(
            f"Generated by {escape(APP_NAME)} v{escape(APP_VERSION)} | "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            small_style,
        ),
    ])

    doc.build(story)
    pdf_bytes = buffer.getvalue()

    # Fail before the caller creates a corrupt output file.
    if not pdf_bytes.startswith(b"%PDF-") or b"%%EOF" not in pdf_bytes[-2048:]:
        raise ValueError("ReportLab returned an incomplete PDF document")

    return pdf_bytes


def get_pdf_filename(session: TestSession) -> str:
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = _attr(session, "result", None)
    result_text = getattr(result, "value", str(result or "Pending"))
    serial = _attr(session, "serial_number", "Battery") or "Battery"
    return f"{serial}_{date_str}_{result_text}.pdf"


@dataclass(frozen=True)
class ReportSaveResult:
    """Result returned after an automatic report-save attempt."""

    success: bool
    folder: str = ""
    csv_path: str = ""
    pdf_path: str = ""
    errors: tuple[str, ...] = ()
    skipped: bool = False


class ReportAutoSaver:
    """Create and atomically save CSV/PDF reports for a finished test."""

    def __init__(
        self,
        root_folder: str | None = None,
        reports_folder: str = "Reports",
    ):
        self.root_folder = root_folder
        self.reports_folder = reports_folder
        self.reset()

    def reset(self, build_id: str = ""):
        """Prepare the saver for a new battery test."""
        self.build_id = (build_id or "").strip()
        self._paths: tuple[str, str] | None = None
        self._completed = False
        self._in_progress = False

    @staticmethod
    def _safe_path_component(value: str, fallback: str) -> str:
        value = (value or "").strip()
        if not value:
            return fallback

        value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value)
        value = re.sub(r"\s+", " ", value).strip(" .")
        return value[:100] or fallback

    def _application_root(self) -> str:
        if self.root_folder:
            return os.path.abspath(self.root_folder)

        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))

        # report_generator.py is inside the core folder.
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _get_paths(self, session: TestSession) -> tuple[str, str]:
        if self._paths:
            return self._paths

        build_folder = self._safe_path_component(
            self.build_id,
            "Unassigned",
        )
        report_dir = os.path.join(
            self._application_root(),
            self.reports_folder,
            build_folder,
        )
        os.makedirs(report_dir, exist_ok=True)

        csv_name = os.path.basename(get_csv_filename(session))
        pdf_name = os.path.basename(get_pdf_filename(session))

        if not csv_name.lower().endswith(".csv"):
            csv_name += ".csv"
        if not pdf_name.lower().endswith(".pdf"):
            pdf_name += ".pdf"

        self._paths = (
            os.path.join(report_dir, csv_name),
            os.path.join(report_dir, pdf_name),
        )
        return self._paths

    @staticmethod
    def _atomic_write_text(path: str, content: str):
        temp_path = path + ".tmp"
        try:
            with open(
                temp_path,
                "w",
                encoding="utf-8",
                newline="",
            ) as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _atomic_write_bytes(path: str, content: bytes):
        temp_path = path + ".tmp"
        try:
            with open(temp_path, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            raise

    def save(
        self,
        session: TestSession | None,
        *,
        force: bool = False,
    ) -> ReportSaveResult:
        """Save CSV and PDF after a test completes or aborts."""
        if session is None:
            return ReportSaveResult(success=False, skipped=True)

        if session.status not in (
            TestStatus.COMPLETE,
            TestStatus.ABORTED,
        ):
            return ReportSaveResult(success=False, skipped=True)

        if self._in_progress:
            return ReportSaveResult(success=False, skipped=True)

        if self._completed and not force:
            csv_path, pdf_path = self._paths or ("", "")
            return ReportSaveResult(
                success=True,
                folder=os.path.dirname(csv_path) if csv_path else "",
                csv_path=csv_path,
                pdf_path=pdf_path,
                skipped=True,
            )

        csv_path, pdf_path = self._get_paths(session)
        errors: list[str] = []
        self._in_progress = True

        try:
            try:
                csv_text = generate_csv(session)
                if not isinstance(csv_text, str):
                    raise TypeError(
                        "CSV generator did not return text data"
                    )
                self._atomic_write_text(csv_path, csv_text)
            except Exception as exc:
                errors.append(f"CSV: {exc}")

            try:
                pdf_bytes = generate_pdf(session)
                if not isinstance(pdf_bytes, (bytes, bytearray)):
                    raise TypeError(
                        "PDF generator did not return binary data"
                    )
                if not pdf_bytes.startswith(b"%PDF-"):
                    raise ValueError(
                        "Generated report does not have a PDF header"
                    )
                if b"%%EOF" not in pdf_bytes[-2048:]:
                    raise ValueError(
                        "Generated PDF report is incomplete"
                    )
                self._atomic_write_bytes(
                    pdf_path,
                    bytes(pdf_bytes),
                )
            except Exception as exc:
                errors.append(f"PDF: {exc}")

            self._completed = not errors
            return ReportSaveResult(
                success=not errors,
                folder=os.path.dirname(csv_path),
                csv_path=csv_path,
                pdf_path=pdf_path,
                errors=tuple(errors),
            )
        finally:
            self._in_progress = False


def _build_discharge_chart(session: TestSession) -> Drawing:
    # Sized for the landscape Letter page used by the graph section.
    drawing = Drawing(9.25 * inch, 6.05 * inch)
    drawing.hAlign = "CENTER"

    chart = LinePlot()
    chart.x = 0.70 * inch
    chart.y = 0.78 * inch
    chart.width = 7.80 * inch
    chart.height = 4.40 * inch

    time_data = list(_attr(session, "time_data", []) or [])
    cell_data = list(_attr(session, "cell_data", []) or [])
    samples = list(_attr(session, "samples", []) or [])

    time_hours = [float(value) / 3600.0 for value in time_data]
    step = max(1, len(time_hours) // 250)
    times = time_hours[::step]

    chart.data = []
    colour_pairs = []
    for index, column in enumerate(cell_data):
        voltages = [float(value) for value in column[::step]]
        points = list(zip(times[:len(voltages)], voltages))
        if not points:
            continue
        chart.data.append(points)
        colour = colors.HexColor(CELL_COLORS[index % len(CELL_COLORS)])
        line_index = len(chart.data) - 1
        chart.lines[line_index].strokeColor = colour
        chart.lines[line_index].strokeWidth = 1.2
        colour_pairs.append((colour, f"C{index + 1}"))

    valid_voltages = [
        float(value)
        for column in cell_data
        for value in column
        if isinstance(value, (int, float)) and value >= 2.0
    ]
    y_min = max(2.0, min(valid_voltages) - 0.1) if valid_voltages else 2.5
    y_max = max(valid_voltages) + 0.2 if valid_voltages else 4.3
    if y_max <= y_min:
        y_max = y_min + 0.5

    chart.xValueAxis.valueMin = 0
    chart.xValueAxis.valueMax = max(time_hours) if time_hours else 1
    if chart.xValueAxis.valueMax <= 0:
        chart.xValueAxis.valueMax = 1
    chart.xValueAxis.labelTextFormat = "%.2f"
    chart.xValueAxis.labels.fontName = "Helvetica"
    chart.xValueAxis.labels.fontSize = 8

    chart.yValueAxis.valueMin = y_min
    chart.yValueAxis.valueMax = y_max
    chart.yValueAxis.labels.fontName = "Helvetica"
    chart.yValueAxis.labels.fontSize = 8

    # Current is mapped onto the voltage axis so it can share one chart.
    current_data = [float(sample.current_ma) / 1000.0 for sample in samples][::step]
    if current_data and times:
        current_min = min(-60.0, min(current_data))
        current_max = max(15.0, max(current_data))
        current_range = current_max - current_min or 1.0
        voltage_range = y_max - y_min
        mapped = [
            y_min + ((value - current_min) / current_range) * voltage_range
            for value in current_data
        ]
        chart.data.append(list(zip(times[:len(mapped)], mapped)))
        current_index = len(chart.data) - 1
        chart.lines[current_index].strokeColor = colors.HexColor("#FF00FF")
        chart.lines[current_index].strokeWidth = 2.2
        colour_pairs.append((colors.HexColor("#FF00FF"), "Current"))

    drawing.add(chart)
    drawing.add(String(
        chart.x + chart.width / 2,
        chart.y - 0.42 * inch,
        "Time (hours)",
        textAnchor="middle",
        fontSize=10,
        fontName="Helvetica-Bold",
    ))
    drawing.add(String(
        0.10 * inch,
        chart.y + chart.height / 2,
        "Voltage (V)",
        textAnchor="middle",
        fontSize=10,
        fontName="Helvetica-Bold",
    ))

    discharge_end = float(_attr(session, "discharge_end_voltage", 3.0))
    if y_min <= discharge_end <= y_max:
        fraction = (discharge_end - y_min) / (y_max - y_min)
        y_position = chart.y + fraction * chart.height
        cutoff_line = Line(chart.x, y_position, chart.x + chart.width, y_position)
        cutoff_line.strokeColor = colors.HexColor("#e67e22")
        cutoff_line.strokeWidth = 1.5
        cutoff_line.strokeDashArray = [6, 3]
        drawing.add(cutoff_line)
        drawing.add(String(
            chart.x + chart.width - 4,
            y_position + 4,
            f"Min {discharge_end:.2f} V",
            textAnchor="end",
            fontSize=8,
            fillColor=colors.HexColor("#e67e22"),
        ))

    if colour_pairs:
        legend = Legend()
        legend.fontName = "Helvetica"
        legend.fontSize = 8
        legend.x = chart.x + 0.10 * inch
        legend.y = chart.y + chart.height + 0.62 * inch
        legend.boxAnchor = "nw"
        legend.alignment = "left"

        # 15 entries (14 cells + current) are arranged as five columns with
        # three rows, matching the wider three-line legend in v1.0.0.
        legend.columnMaximum = 3
        legend.deltax = 92
        legend.deltay = 12
        legend.dx = 8
        legend.dy = 8
        legend.dxTextSpace = 5
        legend.colorNamePairs = colour_pairs
        drawing.add(legend)

    return drawing