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
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics import renderPDF

from core.battery_test import TestSession, TestResult, TestStatus
from core.config import CELL_COLORS, APP_NAME, APP_VERSION, LOGO_PATH, COPPERSTONE_TEAL, COPPERSTONE_GREEN


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
    writer.writerow(['Tech Initials', session.tech_initials])
    writer.writerow(['MFG Date', session.mfg_date])
    writer.writerow(['Battery Age', session.battery_age])
    writer.writerow(['Chemistry', session.chemistry])
    writer.writerow(['Rated Capacity (Ah)', f"{session.rated_capacity_ah:.1f}"])
    writer.writerow(['Measured Capacity (Ah)', f"{session.calculated_capacity_ah:.4f}"])
    writer.writerow(['Measured Capacity (mAh)', f"{session.calculated_capacity_ah * 1000:.1f}"])
    writer.writerow(['Capacity (%)', f"{session.capacity_percent:.1f}"])
    writer.writerow(['Pass Threshold (%)', f"{session.pass_threshold_pct:.0f}"])
    writer.writerow(['Test Stopped By', session.stop_reason])
    writer.writerow(['Result', session.result.value])
    if session.override_reason:
        writer.writerow(['Override Reason', session.override_reason])
    writer.writerow(['Runtime', session.runtime_str])
    writer.writerow(['Storage Voltage (V)', f"{session.storage_voltage:.2f}"])
    writer.writerow(['Discharge End Voltage (V)', f"{session.discharge_end_voltage:.2f}"])
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
        textColor=colors.HexColor(COPPERSTONE_TEAL),
        spaceAfter=6
    )
    h1_style = ParagraphStyle(
        'H1',
        parent=styles['Heading1'],
        fontSize=14,
        textColor=colors.HexColor(COPPERSTONE_TEAL),
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

    # Result color - Updated to Copperstone Green for Pass
    if session.result == TestResult.PASS:
        result_color = colors.HexColor(COPPERSTONE_GREEN)
        result_bg    = colors.HexColor('#eafaf1')
    elif session.result == TestResult.FAIL:
        result_color = colors.HexColor('#e74c3c')
        result_bg    = colors.HexColor('#fdedec')
    else:
        result_color = colors.HexColor('#f39c12')
        result_bg    = colors.HexColor('#fef9e7')

    # ── Page 1: Summary ───────────────────────────────────────────────────────

    import os
    if os.path.exists(LOGO_PATH):
        try:
            from reportlab.platypus import Image
            logo = Image(LOGO_PATH, width=3*inch, height=1*inch, kind='proportional')
            story.append(logo)
            story.append(Spacer(1, 0.15*inch))
        except Exception as e:
            print(f"⚠ Could not add logo to PDF: {e}")

    # Title
    story.append(Paragraph("Battery Test Report", title_style))
    story.append(Paragraph(
        f"{APP_NAME} | v{APP_VERSION}",
        small_style
    ))
    story.append(HRFlowable(width='100%', thickness=2,
                             color=colors.HexColor(COPPERSTONE_TEAL)))
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
        ['Battery Serial', session.serial_number, 'Test Date', date_str],
        ['Chemistry', session.chemistry, 'MFG Date', session.mfg_date],
        ['Rated Capacity', f"{session.rated_capacity_ah:.1f} Ah", 'Battery Age', session.battery_age],
        ['Storage Voltage', f"{session.storage_voltage:.2f} V", 'Runtime', session.runtime_str],
        ['Pass Threshold', f">= {session.pass_threshold_pct:.0f}%", 'Cycle Count (BMS)', str(session.bms_cycle_count)],
        ['Tech Initials', session.tech_initials, 'Test Stopped By', session.stop_reason],
    ]
    info_table = Table(info_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 2*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('FONTNAME',   (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME',   (2,0), (2,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor(COPPERSTONE_TEAL)), # Updated Background
        ('TEXTCOLOR',  (0,0), (0,-1), colors.white),                      # Updated Text Color
        ('BACKGROUND', (2,0), (2,-1), colors.HexColor(COPPERSTONE_TEAL)), # Updated Background
        ('TEXTCOLOR',  (2,0), (2,-1), colors.white),                      # Updated Text Color
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
        ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor(COPPERSTONE_TEAL)),
        ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#f2f9f8')]), # Very light teal alternating
        ('GRID',         (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('ALIGN',        (2,0), (2,-1),  'CENTER'),
        ('TOPPADDING',   (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ('LEFTPADDING',  (0,0), (-1,-1), 8),
    ]))
    for row_idx, row in enumerate(cap_data):
        if row[2] == 'PASS':
            cap_table.setStyle(TableStyle([
                ('TEXTCOLOR',  (2,row_idx), (2,row_idx), colors.HexColor(COPPERSTONE_GREEN)),
                ('FONTNAME',   (2,row_idx), (2,row_idx), 'Helvetica-Bold'),
            ]))
        elif row[2] == 'FAIL':
            cap_table.setStyle(TableStyle([
                ('TEXTCOLOR',  (2,row_idx), (2,row_idx), colors.HexColor('#e74c3c')),
                ('FONTNAME',   (2,row_idx), (2,row_idx), 'Helvetica-Bold'),
            ]))
    story.append(cap_table)

    if session.override_reason:
        story.append(Spacer(1, 0.1*inch))
        story.append(Paragraph(
            f"<b>Override Reason:</b> {session.override_reason}", normal_style
        ))

    if session.bms_temperatures:
        story.append(Spacer(1, 0.1*inch))
        temps = session.bms_temperatures

        if len(temps) == 3:
            temp_str = f"Cells: {temps[0]:.1f}°C, {temps[1]:.1f}°C  |  MOS/BMS: {temps[2]:.1f}°C"
        elif len(temps) == 2:
            temp_str = f"Cells: {temps[0]:.1f}°C, {temps[1]:.1f}°C"
        else:
            temp_str = ', '.join([f"{t:.1f}°C" for t in temps])

        story.append(Paragraph(f"<b>BMS Temperatures:</b> {temp_str}", normal_style))

    if session.health_events:
        story.append(Spacer(1, 0.15*inch))
        story.append(Paragraph("Health Events During Test", h1_style))
        event_data = [['Time (s)', 'Type', 'Cell', 'Voltage', 'Description']]
        for ev in session.health_events[:20]:
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
            ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor(COPPERSTONE_TEAL)),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#f2f9f8')]),
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

    story.append(PageBreak())

    # ── Page 3: Per-Cell Table ────────────────────────────────────────────────

    story.append(Paragraph("Per-Cell Voltage Summary", h1_style))

    if session.samples:
        cell_count  = session.cell_count
        cell_data_t = session.cell_data

        per_cell_data = [['Cell', 'Start (V)', 'End (V)', 'Min (V)', 'Max (V)', 'Drop (V)']]
        for i in range(cell_count):
            col    = cell_data_t[i]
            start  = col[0]
            end    = col[-1]
            mn     = min(col)
            mx     = max(col)
            drop   = start - end

            per_cell_data.append([
                f"Cell {i+1}",
                f"{start:.3f}",
                f"{end:.3f}",
                f"{mn:.3f}",
                f"{mx:.3f}",
                f"{drop:.3f}"
            ])

        cell_table = Table(per_cell_data, colWidths=[1.1*inch]*6)
        cell_table.setStyle(TableStyle([
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('BACKGROUND',   (0,0), (-1,0),  colors.HexColor(COPPERSTONE_TEAL)),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#f2f9f8')]),
            ('GRID',         (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
            ('ALIGN',        (0,0), (-1,-1), 'CENTER'),
            ('TOPPADDING',   (0,0), (-1,-1), 6),
            ('BOTTOMPADDING',(0,0), (-1,-1), 6),
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
    page_width = 7.0 * inch
    page_height = 8.0 * inch

    logical_width = 8.0 * inch
    logical_height = 7.0 * inch

    drawing = Drawing(page_width, page_height)

    from reportlab.graphics.shapes import Group
    g = Group()

    g.translate(0, page_height)
    g.rotate(-90)

    from reportlab.graphics.charts.lineplots import LinePlot
    chart = LinePlot()
    chart.x = 0.8 * inch
    chart.y = 0.5 * inch
    chart.width = logical_width - 1.6 * inch
    chart.height = logical_height - 1.5 * inch

    time_data = session.time_data
    cell_data = session.cell_data
    cell_count = session.cell_count

    time_hours = [t / 3600.0 for t in time_data]
    step = max(1, len(time_hours) // 200)
    t_sub = time_hours[::step]

    chart.data = []
    hex_colors = CELL_COLORS[:cell_count]

    for i in range(cell_count):
        col = cell_data[i]
        v_sub = col[::step]
        points = list(zip(t_sub, v_sub))
        chart.data.append(points)
        chart.lines[i].strokeColor = colors.HexColor(hex_colors[i % len(hex_colors)])
        chart.lines[i].strokeWidth = 1.5

    chart.xValueAxis.valueMin = 0
    chart.xValueAxis.valueMax = max(time_hours) if time_hours else 1
    chart.xValueAxis.labelTextFormat = '%.2f'
    chart.xValueAxis.labels.fontName = 'Helvetica'
    chart.xValueAxis.labels.fontSize = 9

    live = [v for s in session.samples for v in s.voltages if v >= 2.0]
    chart.yValueAxis.valueMin = max(2.0, min(live) - 0.1) if live else 2.5
    chart.yValueAxis.valueMax = max(live) + 0.3 if live else 4.3
    chart.yValueAxis.labels.fontName = 'Helvetica'
    chart.yValueAxis.labels.fontSize = 9

    g.add(chart)

    current_data = [s.current_ma / 1000.0 for s in session.samples]
    current_sub = current_data[::step]

    voltage_range = chart.yValueAxis.valueMax - chart.yValueAxis.valueMin
    current_min, current_max = -60, 15
    current_range = current_max - current_min

    current_mapped = []
    for curr in current_sub:
        normalized = (curr - current_min) / current_range
        mapped_v = chart.yValueAxis.valueMin + (normalized * voltage_range)
        current_mapped.append(mapped_v)

    current_points = list(zip(t_sub, current_mapped))

    current_idx = len(chart.data)
    chart.data.append(current_points)

    # ── UPDATED TO NEON MAGENTA ──────────────────────────────────────────────
    chart.lines[current_idx].strokeColor = colors.HexColor('#FF00FF')
    chart.lines[current_idx].strokeWidth = 3

    from reportlab.graphics.shapes import String, Line as ShapeLine

    x_label = String(
        chart.x + chart.width / 2,
        chart.y - 0.45 * inch,
        'Time (hours)',
        textAnchor='middle',
        fontSize=11,
        fontName='Helvetica-Bold'
    )
    g.add(x_label)

    def add_portrait_horizontal_label(x_pos, y_pos, text):
        tg = Group()
        tg.translate(x_pos, y_pos)
        tg.rotate(90)
        tg.add(String(0, 0, text, textAnchor='middle', fontSize=11, fontName='Helvetica-Bold'))
        g.add(tg)

    add_portrait_horizontal_label(0.15 * inch, chart.y + chart.height / 2, 'Voltage (V)')

    right_x = chart.x + chart.width
    add_portrait_horizontal_label(right_x + 0.5 * inch, chart.y + chart.height / 2, 'Current (A)')

    for curr_val in [0, -15, -30, -45, -60]:
        y_frac = (curr_val - current_min) / current_range
        y_pos = chart.y + y_frac * chart.height

        tick = ShapeLine(
            right_x,
            y_pos,
            right_x + 0.08 * inch,
            y_pos
        )
        tick.strokeColor = colors.black
        tick.strokeWidth = 0.5
        g.add(tick)

        marker = String(
            right_x + 0.12 * inch,
            y_pos - 3,
            f'{curr_val}',
            textAnchor='start',
            fontSize=8,
            fontName='Helvetica'
        )
        g.add(marker)

    discharge_end = session.discharge_end_voltage
    if live:
        y_frac = (discharge_end - chart.yValueAxis.valueMin) / voltage_range
        y_pos = chart.y + y_frac * chart.height

        line = ShapeLine(chart.x, y_pos, right_x, y_pos)
        line.strokeColor = colors.HexColor('#e67e22')
        line.strokeWidth = 2
        line.strokeDashArray = [6, 3]
        g.add(line)

        discharge_label = String(
            right_x - 0.3 * inch,
            y_pos + 4,
            f'Min {discharge_end}V',
            textAnchor='end',
            fontSize=9,
            fontName='Helvetica',
            fillColor=colors.HexColor('#e67e22')
        )
        g.add(discharge_label)

    from reportlab.graphics.charts.legends import Legend
    legend = Legend()
    legend.fontName = 'Helvetica'
    legend.fontSize = 8
    legend.x = chart.x
    legend.y = chart.y + chart.height + 0.6 * inch
    legend.boxAnchor = 'nw'

    # ── FIX FOR LEGEND SPACING & ALIGNMENT ────────────────────────────────────
    legend.alignment = 'left' # Flips the order: Box on left, text closely on the right
    legend.columnMaximum = 3  # Creates exactly 5 columns for 15 items, filling the width cleanly
    legend.deltax = 60        # Width of each column block
    legend.dx = 8             # Color box width
    legend.dy = 8             # Color box height
    legend.dxTextSpace = 5    # Tight gap between box and text

    legend_items = []
    for i in range(cell_count):
        legend_items.append((colors.HexColor(hex_colors[i % len(hex_colors)]), f"C{i + 1}"))
    legend_items.append((colors.HexColor('#FF00FF'), "Current"))
    legend.colorNamePairs = legend_items

    g.add(legend)
    drawing.add(g)

    return drawing
