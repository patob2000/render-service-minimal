from __future__ import annotations

from datetime import date
from pathlib import Path


def _require_reportlab():
    try:
        from reportlab.lib import colors  # noqa: F401
        from reportlab.lib.pagesizes import LETTER  # noqa: F401
        from reportlab.lib.styles import getSampleStyleSheet  # noqa: F401
        from reportlab.platypus import SimpleDocTemplate  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: reportlab. Install with: pip install reportlab"
        ) from e


def build_pdf(output_path: Path) -> None:
    _require_reportlab()

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    title = styles["Title"]
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        spaceBefore=12,
        spaceAfter=6,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        leading=14,
        spaceAfter=6,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="Render Service - Modal + S3",
        author="Francisco Salazar",
    )

    story = []

    # Page 1 - Deliverables
    story.append(Paragraph("Render Service - Migración a Modal + S3 (MVP)", title))
    story.append(Paragraph(f"Fecha: {date.today().isoformat()}", body))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Resumen", h2))
    story.append(
        Paragraph(
            "Se migró el servicio de render (FastAPI + FFmpeg) a Modal para ejecución on-demand, "
            "render asíncrono real fuera del request HTTP, y subida del output a Amazon S3 con URL de descarga.",
            body,
        )
    )

    story.append(Paragraph("Features implementadas", h2))
    features = [
        (
            "API compatible (mismos endpoints)",
            "Se mantuvo el mismo contrato: el frontend llama a un endpoint para crear el render y a otro para consultar el estado.",
        ),
        (
            "Render asíncrono real (no bloquea el request)",
            "Cuando el usuario aprieta “Generar”, el servidor responde rápido con un ID y el render se hace en segundo plano.",
        ),
        (
            "Worker separado para renders pesados (FFmpeg)",
            "El trabajo pesado corre en un proceso aislado, para que el API no se caiga por consumo de CPU/RAM.",
        ),
        (
            "Máximo 4 renders simultáneos",
            "Aunque entren 20 requests, se procesan 4 a la vez; los demás quedan en cola hasta que haya capacidad.",
        ),
        (
            "Descarga de assets por URL antes del render",
            "Imágenes, audios y videos se bajan automáticamente desde sus links antes de ejecutar FFmpeg.",
        ),
        (
            "Control de threads de FFmpeg",
            "Se limita el uso de CPU por render (threads=1 en Modal) para evitar que varios renders se “peleen” el servidor.",
        ),
        (
            "Estado por jobId persistente",
            "Cada render tiene un ID; puedes ver si está en cola, procesando, listo o falló, y ver el error si aplica.",
        ),
        (
            "Subida automática del MP4 a S3",
            "El video final se guarda en el bucket del cliente, evitando depender del disco del servidor.",
        ),
        (
            "Link de descarga (presigned) por 24 horas",
            "Al terminar, se entrega un link temporal para descargar el MP4 sin exponer el bucket públicamente.",
        ),
    ]

    bullets = []
    for title_text, explanation in features:
        bullets.append(
            f"• <b>{title_text}</b><br/>&nbsp;&nbsp;&nbsp;&nbsp;{explanation}"
        )
    story.append(Paragraph("<br/><br/>".join(bullets), body))

    story.append(Paragraph("Mejoras y hardening", h2))
    improvements = [
        "Se corrigieron problemas de packaging/mount en Modal para asegurar imports consistentes del paquete app/.",
        "Se incorporaron dependencias faltantes del runtime Modal (pydantic-settings, python-dotenv, boto3).",
        "Se dejó README con comandos de deploy y smoke tests (incluye test de concurrencia).",
    ]
    story.append(Paragraph("<br/>".join([f"• {i}" for i in improvements]), body))

    story.append(Paragraph("Notas operacionales", h2))
    story.append(
        Paragraph(
            "Credenciales AWS se manejan mediante Modal Secret (render-s3). "
            "No se incluyen secretos en el repositorio.",
            body,
        )
    )

    # Page 2 - Quote
    story.append(PageBreak())
    story.append(Paragraph("Cotización", title))
    story.append(Paragraph("Cliente: Patricio (Pato)", body))
    story.append(Paragraph("Servicio: Implementación MVP Render Service en Modal + S3", body))
    story.append(Spacer(1, 12))

    rows = [
        ["Ítem", "Detalle", "Monto (CLP)"],
        ["Clase inicial (1h)", "Revisión de requerimientos, alcance, riesgos y plan", "$40.000"],
        ["Seteo de ambiente y código", "Rama, venv, dependencias, base de deploy", "$30.000"],
        ["Investigación de solución", "Diseño Modal + límites + storage S3 + presign", "$30.000"],
        ["Desarrollo (2h)", "Implementación API + worker + S3 + fixes", "$100.000"],
        ["Testing y entrega", "Smoke tests, validación y handoff", "$30.000"],
        ["TOTAL", "", "$200.000"],
    ]

    table = Table(rows, colWidths=[1.7 * inch, 3.7 * inch, 1.2 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -2), 0.25, colors.HexColor("#D1D5DB")),
                ("BACKGROUND", (0, 1), (-1, -2), colors.white),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3F4F6")),
                ("GRID", (0, -1), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    story.append(table)
    story.append(Spacer(1, 10))

    story.append(
        Paragraph(
            "Notas: No incluye optimizaciones avanzadas de performance/calidad, observabilidad avanzada, "
            "ni soporte continuo. Presigned URL configurada a 24 horas.",
            body,
        )
    )

    doc.build(story)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output = repo_root / "RenderService_Modal_S3_Reporte_y_Cotizacion.pdf"
    build_pdf(output)
    print(str(output))


if __name__ == "__main__":
    main()

