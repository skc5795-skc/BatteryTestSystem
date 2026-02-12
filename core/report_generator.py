"""
Report Generator
Generates CSV and PDF test reports from a TestSession.
Shared between Desktop and Web apps.
"""

import io
import csv
import time
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                  TableStyle, HRFlowable, PageBreak)
from reportlab.graphics.shapes import Drawing, Line
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics import renderPDF

from core.battery_test import TestSession, TestResult, TestStatus
from core.config import CELL_COLORS, APP_NAME, APP_VERSION


# ── CSV Report ────────────────────────────────────────────────────────────────

def generate_csv(session: TestSession) -> str:
    """
    Generate CSV string from test session.
    Returns filename and CSV content as string.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header block
    writer.writerow(['Battery Test Report'])
    writer.writerow(['Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow(['Battery Serial', session.serial_number])
    writer.writerow(['Chemistry', session.chemistry])
    writer.writerow(['Rated Capacity (Ah)', f"{session.rated_capacity_ah:.1f}"])
    writer.writerow(['Measured Capacity (Ah)', f"{session.calculated_capacity_ah:.4f}"])
    writer.writerow(['Measured Capacity (mAh)', f"{session.calculated_capacity_ah * 1000:.1f}"])
    writer.writerow(['Capacity (%)', f"{session.capacity_percent:.1f}"])
    writer.writerow(['Pass Threshold (%)', f"{session.pass_threshold_pct:.0f}"])
    writer.writerow(['Result', session.result.value])
    if session.override_reason:
        writer.writerow(['Override Reason', session.override_reason])
    writer.writerow(['Runtime', session.runtime_str])
    writer.writerow(['Storage Voltage (V)', f"{session.storage_voltage:.2f}"])
    writer.writerow(['BMS Cycle Count', session.bms_cycle_count])
    writer.writerow([])

    # Health events
    if session.health_events:
        writer.writerow(['Health Events'])
        writer.writerow(['Time (s)', 'Type', 'Cell', 'Voltage (V)', 'Message'])
        for event in session.health_events:
            writer.writerow([
                f"{event['time']:.1f}",
                event['type'],
                event.get('cell', ''),
                f"{event.get('voltage', ''):.3f}" if event.get('voltage') else '',
                event['message']
            ])
        writer.writerow([])

    # Voltage data
    if session.samples:
        cell_count = len(session.samples[0].voltages)
        headers = ['Time (s)', 'Current (mA)'] + [f'Cell {i+1} (V)' for i in range(cell_count)]
        writer.writerow(headers)

        for sample in session.samples:
            row = [f"{sample.timestamp:.1f}", f"{sample.current_ma:.0f}"]
            row += [f"{v:.4f}" for v in sample.voltages]
            writer.writerow(row)

    return output.getvalue()


def get_csv_filename(session: TestSession) -> str:
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    result   = session.result.value
    return f"{session.serial_number}_{date_str}_{result}.csv"


# ── PDF Report ────────────────────────────────────────────────────────────────

def generate_pdf(session: TestSession) -> bytes:
    """
    Generate professional PDF test report.
    Returns PDF as bytes.
    """
    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch,  bottomMargin=0.75*inch
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Custom Styles ─────────────────────────────────────────────────────────
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=22,
        textColor=colors.HexColor('#1a1a2e'),
        spaceAfter=6
    )
    h1_style = ParagraphStyle(
        'H1',
        parent=styles['Heading1'],
        fontSize=14,
        textColor=colors.HexColor('#16213e'),
        spaceBefore=14,
        spaceAfter=6
    )
    normal_style = styles['Normal']
    small_style  = ParagraphStyle(
        'Small',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey
    )

    # Result color
    if session.result == TestResult.PASS:
        result_color = colors.HexColor('#27ae60')
        result_bg    = colors.HexColor('#eafaf1')
    elif session.result == TestResult.FAIL:
        result_color = colors.HexColor('#e74c3c')
        result_bg    = colors.HexColor('#fdedec')
    else:
        result_color = colors.HexColor('#f39c12')
        result_bg    = colors.HexColor('#fef9e7')

    # ── Page 1: Summary ───────────────────────────────────────────────────────

    # Title
    story.append(Paragraph(APP_NAME, title_style))
    story.append(Paragraph(
        f"Battery Discharge Test Report  |  v{APP_VERSION}",
        small_style
    ))
    story.append(HRFlowable(width='100%', thickness=2,
                             color=colors.HexColor('#1a1a2e')))
    story.append(Spacer(1, 0.15*inch))

    # Result banner
    result_table = Table(
        [[Paragraph(
            f"<b>TEST RESULT: {session.result.value}</b>",
            ParagraphStyle('res', fontSize=18, textColor=result_color,
                           alignment=1)
        )]],
        colWidths=[7*inch]
    )
    result_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,-1), result_bg),
        ('BOX',         (0,0), (-1,-1), 1.5, result_color),
        ('TOPPADDING',  (0,0), (-1,-1), 10),
        ('BOTTOMPADDING',(0,0),(-1,-1), 10),
    ]))
    story.append(result_table)
    story.append(Spacer(1, 0.15*inch))

    # Battery info table
    story.append(Paragraph("Battery Information", h1_style))
    date_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    info_data = [
        ['Battery Serial Number', session.serial_number,
         'Test Date', date_str],
        ['Chemistry', session.chemistry,
         'Runtime', session.runtime_str],
        ['Rated Capacity',    f"{session.rated_capacity_ah:.1f} Ah  ({session.rated_capacity_ah*1000:.0f} mAh)",
         'Cycle Count (BMS)', str(session.bms_cycle_count)],
        ['Storage Voltage',   f"{session.storage_voltage:.2f} V",
         'Pass Threshold',    f">= {session.pass_threshold_pct:.0f}%"],
    ]
    info_table = Table(info_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 2*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('FONTNAME',   (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME',   (2,0), (2,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#eef2ff')),
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor('#eef2ff')),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1), 5),
        ('LEFTPADDING',(0,0), (-1,-1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.15*inch))

    # Capacity summary table
    story.append(Paragraph("Capacity Results", h1_style))
    cap_pct = session.capacity_percent
    cap_data = [
        ['Metric', 'Value', 'Status'],
        ['Rated Capacity',
         f"{session.rated_capacity_ah:.2f} Ah  ({session.rated_capacity_ah*1000:.0f} mAh)",
         '—'],
        ['Measured Capacity',
         f"{session.calculated_capacity_ah:.4f} Ah  ({session.calculated_capacity_ah*1000:.1f} mAh)",
         '—'],
        ['Capacity Percentage',
         f"{cap_pct:.1f}%",
         'PASS' if cap_pct >= session.pass_threshold_pct else 'FAIL'],
        ['Pass Threshold',
         f">= {session.pass_threshold_pct:.0f}%",
         '—'],
    ]
    cap_table = Table(cap_data, colWidths=[2.2*inch, 3*inch, 1.8*inch])
    cap_table.setStyle(TableStyle([
        ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTNAME',     (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',     (0,0), (-1,-1), 9),
        ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor('#1a1a2e')),
        ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('GRID',         (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('ALIGN',        (2,0), (2,-1),  'CENTER'),
        ('TOPPADDING',   (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ('LEFTPADDING',  (0,0), (-1,-1), 8),
    ]))
    # Color pass/fail cell
    for row_idx, row in enumerate(cap_data):
        if row[2] == 'PASS':
            cap_table.setStyle(TableStyle([
                ('BACKGROUND', (2,row_idx), (2,row_idx), colors.HexColor('#eafaf1')),
                ('TEXTCOLOR',  (2,row_idx), (2,row_idx), colors.HexColor('#27ae60')),
                ('FONTNAME',   (2,row_idx), (2,row_idx), 'Helvetica-Bold'),
            ]))
        elif row[2] == 'FAIL':
            cap_table.setStyle(TableStyle([
                ('BACKGROUND', (2,row_idx), (2,row_idx), colors.HexColor('#fdedec')),
                ('TEXTCOLOR',  (2,row_idx), (2,row_idx), colors.HexColor('#e74c3c')),
                ('FONTNAME',   (2,row_idx), (2,row_idx), 'Helvetica-Bold'),
            ]))
    story.append(cap_table)

    if session.override_reason:
        story.append(Spacer(1, 0.1*inch))
        story.append(Paragraph(
            f"<b>Override Reason:</b> {session.override_reason}", normal_style
        ))

    # Temperatures
    if session.bms_temperatures:
        story.append(Spacer(1, 0.1*inch))
        temps = ', '.join([f"{t:.1f}°C" for t in session.bms_temperatures])
        story.append(Paragraph(f"<b>BMS Temperatures:</b> {temps}", normal_style))

    # Health events
    if session.health_events:
        story.append(Spacer(1, 0.15*inch))
        story.append(Paragraph("Health Events During Test", h1_style))
        event_data = [['Time (s)', 'Type', 'Cell', 'Voltage', 'Description']]
        for ev in session.health_events[:20]:    # Max 20 events on PDF
            event_data.append([
                f"{ev['time']:.1f}",
                ev['type'],
                str(ev.get('cell', '—')),
                f"{ev.get('voltage', 0):.3f}V" if ev.get('voltage') else '—',
                ev['message']
            ])
        ev_table = Table(event_data,
                         colWidths=[0.7*inch, 1*inch, 0.5*inch, 0.8*inch, 4*inch])
        ev_table.setStyle(TableStyle([
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor('#1a1a2e')),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('GRID',         (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
            ('TOPPADDING',   (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
            ('LEFTPADDING',  (0,0), (-1,-1), 6),
        ]))
        story.append(ev_table)

    story.append(PageBreak())

    # ── Page 2: Discharge Graph ───────────────────────────────────────────────

    story.append(Paragraph("Discharge Curves", h1_style))
    story.append(Spacer(1, 0.1*inch))

    if session.samples and len(session.samples) >= 2:
        drawing = _build_discharge_chart(session)
        story.append(drawing)
    else:
        story.append(Paragraph("Not enough data to generate chart.", normal_style))

    story.append(Spacer(1, 0.2*inch))

    # ── Page 2 cont: Per-Cell Table ───────────────────────────────────────────

    story.append(Paragraph("Per-Cell Voltage Summary", h1_style))

    if session.samples:
        cell_count  = session.cell_count
        cell_data_t = session.cell_data

        # Min, max, start, end per cell
        per_cell_data = [['Cell', 'Start (V)', 'End (V)', 'Min (V)', 'Max (V)',
                           'Drop (V)', 'Status']]
        for i in range(cell_count):
            col    = cell_data_t[i]
            start  = col[0]
            end    = col[-1]
            mn     = min(col)
            mx     = max(col)
            drop   = start - end
            status = 'OK'
            if end < 2.0:
                status = 'DEAD'
            elif end < session.chemistry_config['cell_fail_voltage']:
                status = 'FAIL'
            elif drop > 0.5:
                status = 'WEAK'

            per_cell_data.append([
                f"Cell {i+1}",
                f"{start:.3f}",
                f"{end:.3f}",
                f"{mn:.3f}",
                f"{mx:.3f}",
                f"{drop:.3f}",
                status,
            ])

        cell_table = Table(per_cell_data,
                           colWidths=[0.7*inch]*7)
        cell_table.setStyle(TableStyle([
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor('#1a1a2e')),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('GRID',         (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
            ('ALIGN',        (0,0), (-1,-1), 'CENTER'),
            ('TOPPADDING',   (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
        ]))

        # Color status column
        for row_idx, row in enumerate(per_cell_data[1:], start=1):
            status = row[6]
            if status == 'OK':
                bg = colors.HexColor('#eafaf1')
                tc = colors.HexColor('#27ae60')
            elif status in ('DEAD', 'FAIL'):
                bg = colors.HexColor('#fdedec')
                tc = colors.HexColor('#e74c3c')
            elif status == 'WEAK':
                bg = colors.HexColor('#fef9e7')
                tc = colors.HexColor('#f39c12')
            else:
                continue
            cell_table.setStyle(TableStyle([
                ('BACKGROUND', (6,row_idx), (6,row_idx), bg),
                ('TEXTCOLOR',  (6,row_idx), (6,row_idx), tc),
                ('FONTNAME',   (6,row_idx), (6,row_idx), 'Helvetica-Bold'),
            ]))

        story.append(cell_table)

    # Footer note
    story.append(Spacer(1, 0.3*inch))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph(
        f"Generated by {APP_NAME} v{APP_VERSION}  |  "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        small_style
    ))

    doc.build(story)
    return buffer.getvalue()


def get_pdf_filename(session: TestSession) -> str:
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    result   = session.result.value
    return f"{session.serial_number}_{date_str}_{result}.pdf"


# ── Chart Builder ─────────────────────────────────────────────────────────────

def _build_discharge_chart(session: TestSession) -> Drawing:
    """Build a ReportLab LinePlot of the discharge curves"""
    width  = 7.0 * inch
    height = 3.5 * inch

    drawing = Drawing(width, height)
    chart   = LinePlot()
    chart.x = 0.6 * inch
    chart.y = 0.4 * inch
    chart.width  = width  - 1.0 * inch
    chart.height = height - 0.6 * inch

    time_data  = session.time_data
    cell_data  = session.cell_data
    cell_count = session.cell_count

    # Subsample to max 200 points for readability
    step = max(1, len(time_data) // 200)
    t_sub = time_data[::step]

    chart.data = []
    hex_colors = CELL_COLORS[:cell_count]

    for i in range(cell_count):
        col    = cell_data[i]
        v_sub  = col[::step]
        points = list(zip(t_sub, v_sub))
        chart.data.append(points)

        chart.lines[i].strokeColor = colors.HexColor(hex_colors[i % len(hex_colors)])
        chart.lines[i].strokeWidth = 1.2

    # Axes
    chart.xValueAxis.valueMin   = 0
    chart.xValueAxis.valueMax   = max(time_data) if time_data else 1
    chart.xValueAxis.labelTextFormat = '%d'

    live = [v for s in session.samples for v in s.voltages if v >= 2.0]
    chart.yValueAxis.valueMin = max(2.0, min(live) - 0.1) if live else 2.5
    chart.yValueAxis.valueMax = max(live) + 0.05 if live else 4.3

    drawing.add(chart)

    # Storage voltage line
    x_start = chart.x
    x_end   = chart.x + chart.width
    if live:
        y_range  = chart.yValueAxis.valueMax - chart.yValueAxis.valueMin
        y_ratio  = (session.storage_voltage - chart.yValueAxis.valueMin) / y_range
        y_pos    = chart.y + (y_ratio * chart.height)
        line     = Line(x_start, y_pos, x_end, y_pos)
        line.strokeColor = colors.HexColor('#e67e22')
        line.strokeWidth = 1.5
        line.strokeDashArray = [4, 3]
        drawing.add(line)

    return drawing
