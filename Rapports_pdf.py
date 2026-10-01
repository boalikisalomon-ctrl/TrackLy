import io
from datetime import datetime
from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generer_pdf_rapport(titre_periode, nom_service, nom_employe, stats_globales, synthese_employes, lignes_presences):
    """
    Génère un document PDF complet, élégant et imprimable pour le rapport d'assiduité.
    Retourne un buffer io.BytesIO contenant le fichier binaire PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=portrait(A4),
        leftMargin=25,
        rightMargin=25,
        topMargin=25,
        bottomMargin=25
    )

    styles = getSampleStyleSheet()

    # Styles personnalisés
    style_titre = ParagraphStyle(
        'TitreRapport',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#1a2733'),
        spaceAfter=4
    )

    style_sub = ParagraphStyle(
        'SousTitreRapport',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#64748b'),
        spaceAfter=14
    )

    style_section = ParagraphStyle(
        'SectionTitre',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1a2733'),
        spaceBefore=12,
        spaceAfter=6
    )

    style_cell = ParagraphStyle(
        'CelluleTexte',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1e293b')
    )

    style_cell_bold = ParagraphStyle(
        'CelluleTexteBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1e293b')
    )

    elements = []

    # 1. En-tête
    elements.append(Paragraph("RAPPORT D'ASSIDUITÉ ET DE PRÉSENCE", style_titre))
    date_edition = datetime.now().strftime("%d/%m/%Y à %H:%M:%S")
    info_text = f"<b>Période :</b> {titre_periode} &nbsp;|&nbsp; <b>Département :</b> {nom_service} &nbsp;|&nbsp; <b>Collaborateur :</b> {nom_employe} &nbsp;|&nbsp; <b>Édité le :</b> {date_edition}"
    elements.append(Paragraph(info_text, style_sub))

    # 2. Tableau des KPIs (Indicateurs clés)
    elements.append(Paragraph("Indicateurs globaux de la période", style_section))

    kpi_headers = [
        "Présences",
        "À l'heure",
        "Retards",
        "Taux Ponctualité",
        "Total Heures",
        "Départs pointés"
    ]
    kpi_values = [
        str(stats_globales.get("total_presences", 0)),
        f"{stats_globales.get('total_a_l_heure', 0)} ({stats_globales.get('pourcentage_a_l_heure', 0)}%)",
        f"{stats_globales.get('total_retards', 0)} ({stats_globales.get('pourcentage_retards', 0)}%)",
        f"{stats_globales.get('pourcentage_a_l_heure', 0)}%",
        stats_globales.get("total_heures_formatees", "0m"),
        f"{stats_globales.get('total_departs_pointes', 0)} ({stats_globales.get('pourcentage_departs', 0)}%)"
    ]

    t_kpi = Table([kpi_headers, kpi_values], colWidths=[90, 92, 92, 92, 90, 90])
    t_kpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a2733')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f8fafc')),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(t_kpi)
    elements.append(Spacer(1, 14))

    # 3. Tableau Récapitulatif par Collaborateur
    if synthese_employes:
        elements.append(Paragraph("Synthèse par collaborateur", style_section))

        synth_head = [
            "Employé",
            "Département",
            "Jours",
            "Heures faites",
            "À l'heure",
            "Retards",
            "% Ponctualité",
            "% Départs"
        ]

        synth_rows = [synth_head]
        for e in synthese_employes:
            synth_rows.append([
                Paragraph(e["nom"], style_cell_bold),
                Paragraph(e["service"] or "–", style_cell),
                str(e["nb_presences"]),
                e["heures_str"],
                str(e["nb_a_l_heure"]),
                str(e["nb_retards"]),
                f"{e['pct_ponctualite']}%",
                f"{e['pct_departs']}%"
            ])

        t_synth = Table(synth_rows, colWidths=[120, 85, 45, 75, 55, 55, 60, 50])
        t_synth_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]
        # Alternance de couleurs (zebra rows)
        for i in range(1, len(synth_rows)):
            bg = colors.HexColor('#f8fafc') if i % 2 == 0 else colors.white
            t_synth_style.append(('BACKGROUND', (0, i), (-1, i), bg))

        t_synth.setStyle(TableStyle(t_synth_style))
        elements.append(t_synth)
        elements.append(Spacer(1, 14))

    # 4. Détail journalier des pointages
    if lignes_presences:
        elements.append(Paragraph(f"Détail chronologique des pointages ({len(lignes_presences)} journées)", style_section))

        det_head = [
            "Date",
            "Employé",
            "Département",
            "Arrivée",
            "Départ",
            "Durée",
            "Statut"
        ]

        det_rows = [det_head]
        for l in lignes_presences:
            statut_txt = l["statut"]
            det_rows.append([
                l["date"],
                Paragraph(l["nom"], style_cell),
                Paragraph(l["service"] or "–", style_cell),
                l["heure_arrivee"] or "–",
                l["heure_depart"] or "–",
                l["duree_formatee"],
                statut_txt
            ])

        t_det = Table(det_rows, colWidths=[65, 120, 85, 65, 65, 70, 75])
        t_det_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a2733')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        for i in range(1, len(det_rows)):
            bg = colors.HexColor('#f8fafc') if i % 2 == 0 else colors.white
            t_det_style.append(('BACKGROUND', (0, i), (-1, i), bg))
            # Coloration du statut
            stat = det_rows[i][6]
            if "retard" in stat:
                t_det_style.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#d97706')))
                t_det_style.append(('FONTNAME', (6, i), (6, i), 'Helvetica-Bold'))
            elif "présent" in stat or "present" in stat:
                t_det_style.append(('TEXTCOLOR', (6, i), (6, i), colors.HexColor('#16a34a')))

        t_det.setStyle(TableStyle(t_det_style))
        elements.append(t_det)

    doc.build(elements)
    buffer.seek(0)
    return buffer
