"""Realistic Medical Literature Sample Corpus Generator.
Generates 100-150 test documents covering DOCX, DOC, PDF, Scanned PDF,
Hindi, English, Tables, Long documents, Duplicates, and Corrupted files.
"""

from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import docx
import pymupdf

CORPUS_ROOT = Path("/home/ubuntu/searchengine/sample_corpus")


CARDIOLOGY_TOPICS = [
    {
        "title": "Left Main Coronary Artery Revascularization Guidelines",
        "abbrev": "LM",
        "description": "Left Main (LM) coronary artery disease management using coronary artery bypass grafting (CABG) versus percutaneous coronary intervention (PCI). Evaluation of SYNTAX score, anatomical suitability, and long-term mortality."
    },
    {
        "title": "Chronic Total Occlusion PCI Techniques and Outcomes",
        "abbrev": "CTO",
        "description": "Retrograde and antegrade approaches for Chronic Total Occlusion (CTO) crossing. Wire escalation algorithms, dissection and re-entry techniques (CrossBoss and Stingray), and microcatheter selection."
    },
    {
        "title": "Excimer Laser Coronary Atherectomy in Complex Calcified Lesions",
        "abbrev": "ELCA",
        "description": "Application of Excimer Laser Coronary Atherectomy (ELCA) in under-expanded stents, chronic total occlusions, and severe coronary artery calcification. Laser fluence and repetition rate parameters."
    },
    {
        "title": "Intravascular Ultrasound for Stent Optimization",
        "abbrev": "IVUS",
        "description": "Clinical utility of Intravascular Ultrasound (IVUS) in pre-procedural sizing, reference vessel diameter calculation, minimum lumen area (MLA) assessment, and post-stent expansion verification."
    },
    {
        "title": "Optical Coherence Tomography High-Resolution Plaque Assessment",
        "abbrev": "OCT",
        "description": "Optical Coherence Tomography (OCT) with 10-micron axial resolution. Differentiation of thin-cap fibroatheroma (TCFA), plaque erosion, macrophage infiltration, and stent strut malapposition."
    },
    {
        "title": "Intravascular Lithotripsy for Severely Calcified Coronary Arteries",
        "abbrev": "IVL",
        "description": "Pulsed acoustic pressure waves via Intravascular Lithotripsy (IVL) Shockwave system. Circumferential calcium fracture without soft tissue trauma, improving stent deliverability and compliance."
    },
    {
        "title": "Management of Drug-Eluting In-Stent Restenosis",
        "abbrev": "ISR",
        "description": "Pathophysiological mechanisms of In-Stent Restenosis (ISR) including neoatherosclerosis and stent under-expansion. Treatment with drug-coated balloons (DCB) versus repeat stenting with bioresorbable scaffolds."
    },
    {
        "title": "Transcatheter Aortic Valve Implantation Clinical Registries",
        "abbrev": "TAVI",
        "description": "Long-term outcomes of Transcatheter Aortic Valve Implantation (TAVI / TAVR) in low, intermediate, and high surgical risk patients. Pacemaker implantation rates, paravalvular regurgitation, and leaflet thrombosis."
    },
    {
        "title": "Bifurcation Stenting Strategies and Provisional Approach",
        "abbrev": "Bifurcation",
        "description": "Evaluation of provisional 1-stent technique versus planned 2-stent techniques (DK-crush, Culotte, T-and-protrusion). Proximal optimization technique (POT) and kissing balloon inflation protocols."
    },
    {
        "title": "Fractional Flow Reserve and Instantaneous Wave-Free Ratio",
        "abbrev": "FFR-iFR",
        "description": "Physiological lesion assessment comparing hyperemic Fractional Flow Reserve (FFR cutoff 0.80) and resting Instantaneous Wave-Free Ratio (iFR cutoff 0.89) in guiding coronary revascularization."
    }
]

HINDI_TOPICS = [
    {
        "title": "कोरोनरी धमनी रोग और एंजियोप्लास्टी दिशानिर्देश",
        "content": "कोरोनरी धमनी रोग (Coronary Artery Disease - CAD) हृदय की मांसपेशियों में रक्त प्रवाह में कमी के कारण होता है। एंजियोप्लास्टी और स्टेंट प्रत्यारोपण (Stent Implantation) संकुचित धमनियों को खोलने में अत्यधिक प्रभावी हैं। अल्ट्रासाउंड (IVUS) और ओसीटी (OCT) का उपयोग स्टेंट विस्तार को अनुकूलित करने के लिए किया जाता है।"
    },
    {
        "title": "क्रॉनिक टोटल ऑक्लूजन (CTO) उपचार और तकनीक",
        "content": "क्रॉनिक टोटल ऑक्लूजन (CTO) कोरोनरी धमनी का पूर्ण रुकावट है जो कम से कम 3 महीने तक बना रहता है। नई कैथीeter तकनीकों और माइक्रो-गाइडवायर के उपयोग से सीटीओ एंजियोप्लास्टी की सफलता दर 85% से अधिक हो गई है।"
    },
    {
        "title": "इंट्रावास्कुलर लिथोट्रिप्सी (IVL) द्वारा कैल्सीफाइड घाव उपचार",
        "content": "गंभीर रूप से कैल्सीफाइड कोरोनरी धमनियों के लिए इंट्रावास्कुलर लिथोट्रिप्सी (IVL) सुरक्षित ध्वनि तरंगों का उपयोग करके कैल्शियम को तोड़ती है। इससे स्टेंट पूरी तरह से फैल पाता है और इन-स्टेंट रेस्टेनोसिस (ISR) का जोखिम घटता है।"
    }
]


def ensure_dirs():
    for sub in [
        "docx_trials",
        "pdf_guidelines",
        "legacy_doc",
        "scanned_pdf",
        "mixed_pdf",
        "hindi_literature",
        "txt_summaries",
        "backup_duplicates",
        "corrupted"
    ]:
        (CORPUS_ROOT / sub).mkdir(parents=True, exist_ok=True)


def create_docx_documents(count: int = 35):
    """Generate rich medical DOCX files with tables, headers, footers, headings, and terms."""
    out_dir = CORPUS_ROOT / "docx_trials"

    for i in range(count):
        topic = CARDIOLOGY_TOPICS[i % len(CARDIOLOGY_TOPICS)]
        doc = docx.Document()

        # Set title in core properties
        doc.core_properties.title = f"{topic['title']} - Trial Report Vol {i+1}"
        doc.core_properties.author = "Cardiovascular Interventional Society"

        # Header / Footer
        section = doc.sections[0]
        header = section.header
        hp = header.paragraphs[0]
        hp.text = f"JOURNAL OF INTERVENTIONAL CARDIOLOGY — {topic['abbrev']} STUDY GROUP"

        footer = section.footer
        fp = footer.paragraphs[0]
        fp.text = f"Confidential Medical Review • Page {i+1} • Study ID: MED-2026-{1000+i}"

        # Title
        doc.add_heading(f"{topic['title']} (Study {i+1})", level=0)
        doc.add_heading(f"1. Executive Summary & Clinical Background ({topic['abbrev']})", level=1)
        doc.add_paragraph(topic["description"])
        doc.add_paragraph(
            f"In this cohort study of {200 + i * 25} randomized patients, interventional evaluation "
            f"demonstrated significant reduction in Major Adverse Cardiac Events (MACE). "
            f"Standard imaging protocols including IVUS, OCT, and ELCA were employed where indicated."
        )

        doc.add_heading("2. Patient Demographics & Baseline Characteristics", level=1)
        # Add rich clinical table
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = "Clinical Variable"
        hdr_cells[1].text = "Intervention Arm (n=150)"
        hdr_cells[2].text = "Control Arm (n=150)"
        hdr_cells[3].text = "p-Value"

        variables = [
            ("Mean Age (years)", f"{64.2 + (i % 5):.1f} ± 8.2", f"{65.1 + (i % 5):.1f} ± 7.9", "0.42"),
            ("Diabetes Mellitus (%)", f"{32 + (i % 10)}%", f"{34 + (i % 10)}%", "0.68"),
            ("Left Main (LM) Stenosis (%)", f"{78 + (i % 8)}%", f"{76 + (i % 8)}%", "0.55"),
            ("Reference Vessel Diameter (mm)", f"{3.25 + (i % 4)*0.25:.2f}", f"{3.20 + (i % 4)*0.25:.2f}", "0.71"),
            ("Minimum Lumen Area (MLA, mm²)", f"{2.1 + (i % 3)*0.1:.2f}", f"{2.2 + (i % 3)*0.1:.2f}", "0.64"),
            ("Post-Procedure MACE at 12M (%)", f"{4.2 + (i % 2):.1f}%", f"{8.9 + (i % 2):.1f}%", "<0.001"),
        ]
        for row_data in variables:
            row_cells = table.add_row().cells
            for idx, text in enumerate(row_data):
                row_cells[idx].text = text

        doc.add_heading("3. Interventional Procedure and Hemodynamics", level=1)
        doc.add_paragraph(
            f"Pre-dilation was performed using non-compliant balloons up to nominal pressure. "
            f"Intravascular lithotripsy (IVL) was administered with 80 acoustic pulses in calcified rings. "
            f"Stent post-dilation confirmed minimal stent area (MSA) > 80% of reference vessel area."
        )

        filename = f"Trial_{i+1:03d}_{topic['abbrev']}_{topic['title'][:30].replace(' ', '_')}.docx"
        doc.save(str(out_dir / filename))

    print(f"Generated {count} DOCX files in {out_dir}")


def create_pdf_documents(count: int = 35):
    """Generate multi-page medical PDF files with text, tables, and headers."""
    out_dir = CORPUS_ROOT / "pdf_guidelines"

    for i in range(count):
        topic = CARDIOLOGY_TOPICS[i % len(CARDIOLOGY_TOPICS)]
        doc = pymupdf.open()

        num_pages = 2 + (i % 6)  # 2 to 7 pages
        for page_idx in range(num_pages):
            page = doc.new_page(width=595, height=842)  # A4 size

            # Header
            page.insert_text(
                (50, 40),
                f"INTERNATIONAL CARDIOLOGY GUIDELINE 2026 — {topic['abbrev']}",
                fontsize=9,
                color=(0.4, 0.4, 0.4)
            )

            # Footer
            page.insert_text(
                (50, 810),
                f"Page {page_idx + 1} of {num_pages} • Document ID: REF-PDF-{2000 + i}",
                fontsize=8,
                color=(0.5, 0.5, 0.5)
            )

            if page_idx == 0:
                # Page 1: Title and Introduction
                page.insert_text((50, 90), f"{topic['title']}", fontsize=18, color=(0.1, 0.2, 0.5))
                page.insert_text((50, 120), f"Clinical Consensus Document — Part {i+1}", fontsize=12, color=(0.3, 0.3, 0.3))

                body_text = (
                    f"Background and Rationale:\n\n"
                    f"{topic['description']}\n\n"
                    f"Coronary artery disease involving complex anatomical subsets presents significant challenges. "
                    f"Technological advances including Intravascular Ultrasound (IVUS), Optical Coherence Tomography (OCT), "
                    f"Excimer Laser Coronary Atherectomy (ELCA), and Intravascular Lithotripsy (IVL) have revolutionized "
                    f"lesion preparation and stent implantation."
                )
                page.insert_textbox(pymupdf.Rect(50, 150, 545, 380), body_text, fontsize=10, lineheight=1.4)

                section2 = (
                    f"Indication Criteria for {topic['abbrev']}:\n\n"
                    f"1. Hemodynamic instability or ongoing ischemia with FFR < 0.80 or resting iFR < 0.89.\n"
                    f"2. Severe calcification precluding stent delivery: recommended upfront treatment with IVL or ELCA.\n"
                    f"3. In-Stent Restenosis (ISR): comprehensive assessment for under-expansion or neoatherosclerosis via OCT.\n"
                    f"4. Left Main (LM) bifurcation disease requiring dedicated provisional or dual-stent strategy."
                )
                page.insert_textbox(pymupdf.Rect(50, 400, 545, 650), section2, fontsize=10, lineheight=1.4)
            else:
                # Subsequent pages: Detailed clinical tables and recommendations
                page.insert_text((50, 80), f"Section {page_idx + 1}: Technical Specifications and Evidence Review", fontsize=14, color=(0.1, 0.2, 0.5))

                p_text = (
                    f"Detailed Procedural Steps (Protocol Step {page_idx}):\n\n"
                    f"Radial access with 6F or 7F guide catheter is standard. Anticoagulation achieved with unfractionated "
                    f"heparin targeting an activated clotting time (ACT) of 250-300 seconds. "
                    f"Guide catheter extension (GuideLiner) is recommended for deep vessel support in tortuous calcified anatomy.\n\n"
                    f"Stent sizing must adhere to distal reference vessel external elastic lamina (EEL) measured by IVUS. "
                    f"Post-dilation with high pressure non-compliant balloon (18-24 atm) is mandatory to prevent acute stent thrombosis."
                )
                page.insert_textbox(pymupdf.Rect(50, 110, 545, 300), p_text, fontsize=10, lineheight=1.4)

                # Simulated table
                table_text = (
                    f"Table {page_idx}.1 — Nominal Pressures and Burst Pressures\n"
                    f"--------------------------------------------------------------------------------\n"
                    f"Stent Diameter (mm) | Nominal (atm) | RBP (atm) | Target Minimum Area (mm²)\n"
                    f"2.50 mm             | 9.0 atm       | 16.0 atm  | 4.5 mm²\n"
                    f"3.00 mm             | 9.0 atm       | 18.0 atm  | 5.5 mm²\n"
                    f"3.50 mm             | 10.0 atm      | 18.0 atm  | 7.0 mm²\n"
                    f"4.00 mm (LM)        | 10.0 atm      | 20.0 atm  | 8.5 mm²\n"
                    f"--------------------------------------------------------------------------------\n"
                    f"RBP: Rated Burst Pressure; LM: Left Main."
                )
                page.insert_textbox(pymupdf.Rect(50, 320, 545, 520), table_text, fontsize=9, fontname="cour")

        doc.set_metadata({
            "title": f"Guideline on {topic['title']}",
            "author": "Interventional Cardiology Committee",
            "subject": f"{topic['abbrev']} Clinical Standards"
        })

        filename = f"Guideline_{i+1:03d}_{topic['abbrev']}.pdf"
        doc.save(str(out_dir / filename))
        doc.close()

    print(f"Generated {count} PDF files in {out_dir}")


def create_legacy_doc_documents(count: int = 15):
    """Generate real legacy Word 97-2003 .doc files using LibreOffice headless conversion."""
    out_dir = CORPUS_ROOT / "legacy_doc"

    with tempfile.TemporaryDirectory(prefix="gen_doc_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        for i in range(count):
            topic = CARDIOLOGY_TOPICS[i % len(CARDIOLOGY_TOPICS)]
            doc = docx.Document()
            doc.add_heading(f"Legacy Archive: {topic['title']} (Year 2002)", level=0)
            doc.add_paragraph(
                f"Historical registry data regarding {topic['abbrev']} interventions. "
                f"Early trials established the baseline safety of bare-metal stents (BMS) and balloon angioplasty. "
                f"Restenosis rates (ISR) historically reached 20-30% before the advent of drug-eluting stents."
            )
            doc.add_paragraph(
                f"Diagnostic catheterization was performed using femoral cutdown or standard Judkins catheters. "
                f"Hemodynamic monitoring measured aortic pressure, left ventricular end-diastolic pressure (LVEDP), "
                f"and coronary sinus saturation."
            )

            src_docx = tmp_path / f"temp_{i}.docx"
            doc.save(str(src_docx))

            # Convert to binary .doc via LibreOffice
            cmd = ["libreoffice", "--headless", "--convert-to", "doc", str(src_docx), "--outdir", str(out_dir)]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            # Rename to final clean name
            gen_doc = out_dir / f"temp_{i}.doc"
            final_doc = out_dir / f"Archive_{i+1:03d}_{topic['abbrev']}_Historical_Registry.doc"
            if gen_doc.exists():
                shutil.move(str(gen_doc), str(final_doc))

    print(f"Generated {count} legacy .doc files in {out_dir}")


def create_scanned_pdf_documents(count: int = 15):
    """Generate scanned (image-only) PDFs to trigger Tesseract OCR."""
    out_dir = CORPUS_ROOT / "scanned_pdf"
    font_en_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_hi_path = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"

    for i in range(count):
        topic = CARDIOLOGY_TOPICS[i % len(CARDIOLOGY_TOPICS)]

        # Create high-resolution PIL image
        img_w, img_h = 1600, 2200
        img = Image.new("RGB", (img_w, img_h), color="#ffffff")
        draw = ImageDraw.Draw(img)

        # Load fonts
        try:
            fnt_title = ImageFont.truetype(font_en_path, 48)
            fnt_body = ImageFont.truetype(font_en_path, 32)
            fnt_small = ImageFont.truetype(font_en_path, 24)
            fnt_hindi = ImageFont.truetype(font_hi_path, 32)
        except Exception:
            fnt_title = ImageFont.load_default()
            fnt_body = ImageFont.load_default()
            fnt_small = ImageFont.load_default()
            fnt_hindi = ImageFont.load_default()

        # Draw medical scanned form layout
        draw.rectangle([(80, 80), (img_w - 80, img_h - 80)], outline="#666666", width=3)
        draw.text((120, 120), f"HOSPITAL CARDIOLOGY CATH LAB RECORD #{i+1:04d}", fill="#111111", font=fnt_title)
        draw.line([(120, 190), (img_w - 120, 190)], fill="#333333", width=2)

        # Body text with abbreviations
        draw.text((120, 230), f"Procedure: Coronary Angiogram & {topic['abbrev']} Intervention", fill="#222222", font=fnt_body)
        draw.text((120, 290), f"Indication: {topic['title']}", fill="#222222", font=fnt_body)
        draw.text((120, 350), f"Lesion Analysis: Severe calcification in Left Main (LM) and LAD.", fill="#222222", font=fnt_body)
        draw.text((120, 410), f"Intravascular Imaging: IVUS and OCT used for pre-dilation sizing.", fill="#222222", font=fnt_body)
        draw.text((120, 470), f"Atherectomy: Excimer Laser (ELCA) and Intravascular Lithotripsy (IVL) applied.", fill="#222222", font=fnt_body)
        draw.text((120, 530), f"Outcome: Stent fully expanded, 0% residual stenosis, TIMI 3 flow.", fill="#222222", font=fnt_body)

        if i % 2 == 1:
            # Add Hindi text line
            hindi_sample = HINDI_TOPICS[i % len(HINDI_TOPICS)]
            draw.text((120, 620), f"हिंदी रिपोर्ट: {hindi_sample['title']}", fill="#222222", font=fnt_hindi)
            draw.text((120, 680), f"रोग निदान: {hindi_sample['content'][:90]}...", fill="#222222", font=fnt_hindi)

        draw.text((120, img_h - 140), f"Scanned Medical Document • Verified by Attending Cardiologist", fill="#666666", font=fnt_small)

        # Convert image to PDF page
        pdf_doc = pymupdf.open()
        img_bytes_io = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(img_bytes_io.name, "PNG")

        page = pdf_doc.new_page(width=595, height=842)
        page.insert_image(pymupdf.Rect(0, 0, 595, 842), filename=img_bytes_io.name)

        filename = f"Scanned_CathReport_{i+1:03d}_{topic['abbrev']}.pdf"
        pdf_doc.save(str(out_dir / filename))
        pdf_doc.close()
        os.unlink(img_bytes_io.name)

    print(f"Generated {count} scanned PDFs in {out_dir}")


def create_mixed_pdf_documents(count: int = 10):
    """Generate PDFs with mixed native text on page 1 and scanned image on page 2."""
    out_dir = CORPUS_ROOT / "mixed_pdf"
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    for i in range(count):
        topic = CARDIOLOGY_TOPICS[i % len(CARDIOLOGY_TOPICS)]
        doc = pymupdf.open()

        # Page 1: Native digital text
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((50, 50), f"MIXED PROTOCOL STUDY: {topic['title']}", fontsize=14, color=(0.1, 0.2, 0.6))
        body = (
            f"Page 1 contains native digital text for rapid indexing.\n\n"
            f"The evaluation of {topic['abbrev']} requires multimodal imaging.\n"
            f"Patients undergoing interventional revascularization for Left Main (LM) or CTO disease "
            f"exhibited superior clinical outcomes when IVUS guidance was documented."
        )
        p1.insert_textbox(pymupdf.Rect(50, 80, 545, 300), body, fontsize=10)

        # Page 2: Scanned chart image
        img = Image.new("RGB", (1200, 1600), color="#ffffff")
        draw = ImageDraw.Draw(img)
        try:
            fnt = ImageFont.truetype(font_path, 36)
        except Exception:
            fnt = ImageFont.load_default()

        draw.text((100, 100), f"SCANNED ATTACHMENT: Angiographic Run #{i+1}", fill="#000000", font=fnt)
        draw.text((100, 200), f"IVUS MLA: 3.8 mm² | IVL Pulses: 80 | Stent: 3.5 x 28 mm", fill="#111111", font=fnt)
        draw.text((100, 300), f"Residual In-Stent Restenosis (ISR): None.", fill="#111111", font=fnt)

        img_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(img_tmp.name, "PNG")

        p2 = doc.new_page(width=595, height=842)
        p2.insert_image(pymupdf.Rect(0, 0, 595, 842), filename=img_tmp.name)

        filename = f"Mixed_Record_{i+1:03d}_{topic['abbrev']}.pdf"
        doc.save(str(out_dir / filename))
        doc.close()
        os.unlink(img_tmp.name)

    print(f"Generated {count} mixed PDFs in {out_dir}")


def create_hindi_documents(count: int = 10):
    """Generate pure Hindi medical literature in DOCX and PDF."""
    out_dir = CORPUS_ROOT / "hindi_literature"

    for i in range(count):
        h = HINDI_TOPICS[i % len(HINDI_TOPICS)]

        # 1. Hindi DOCX
        doc = docx.Document()
        doc.core_properties.title = h["title"]
        doc.add_heading(f"{h['title']} - भाग {i+1}", level=0)
        doc.add_paragraph(h["content"])
        doc.add_paragraph(
            "हृदय रोग विशेषज्ञ (Cardiologist) द्वारा नियमित जांच आवश्यक है। "
            "धमनी की रुकावट (Arterial Blockage) को हटाने के लिए आधुनिक तकनीकें जैसे "
            "आईवीयूएस (IVUS) और ओसीटी (OCT) महत्वपूर्ण परिणाम देती हैं।"
        )
        doc.save(str(out_dir / f"Hindi_Clinical_{i+1:03d}.docx"))

        # 2. Hindi PDF
        pdf = pymupdf.open()
        page = pdf.new_page(width=595, height=842)
        font_name = "noto_hi"
        page.insert_font(fontname=font_name, fontfile="/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf")

        page.insert_text((50, 80), f"{h['title']} (अध्ययन {i+1})", fontname=font_name, fontsize=16)
        page.insert_textbox(
            pymupdf.Rect(50, 120, 545, 600),
            f"{h['content']}\n\n"
            f"कार्डियोलॉजी विभाग: एंजियोप्लास्टी और स्टेंट प्रत्यारोपण के बाद दवाइयां समय पर लेना अनिवार्य है। "
            f"कोरोनरी धमनियों में कैल्शियम की मौजूदगी के लिए इंट्रावास्कुलर लिथोट्रिप्सी (IVL) प्रभावी समाधान है।",
            fontname=font_name,
            fontsize=11,
            lineheight=1.5
        )
        pdf.save(str(out_dir / f"Hindi_Guideline_{i+1:03d}.pdf"))
        pdf.close()

    print(f"Generated {count * 2} Hindi documents in {out_dir}")


def create_txt_documents(count: int = 10):
    """Generate plain text clinical summaries and discharge notes."""
    out_dir = CORPUS_ROOT / "txt_summaries"

    for i in range(count):
        topic = CARDIOLOGY_TOPICS[i % len(CARDIOLOGY_TOPICS)]
        lines = [
            f"DISCHARGE SUMMARY & CATH REPORT — CASE #{3000 + i}",
            "=" * 60,
            f"Patient Diagnosis: Complex CAD with {topic['title']}",
            f"Primary Operator: Dr. Interventionalist, MD",
            f"Procedure Performed: Percutaneous Coronary Intervention with {topic['abbrev']}",
            "",
            "PROCEDURE DESCRIPTION:",
            f"Selective angiogram confirmed severe narrowing. {topic['description']}",
            "Lesion preparation was initiated with semi-compliant balloons.",
            "Intravascular ultrasound (IVUS) confirmed reference diameter of 3.5mm.",
            "Drug-eluting stent deployed with post-dilation at 18 atm.",
            "Final angiogram showed TIMI 3 flow without dissection or distal embolization.",
            "",
            "DISCHARGE MEDICATIONS:",
            "1. Aspirin 81 mg daily",
            "2. Ticagrelor 90 mg BID",
            "3. Atorvastatin 80 mg daily",
            "4. Metoprolol succinate 50 mg daily",
            "=" * 60,
            "End of Clinical Summary."
        ]
        text_content = "\n".join(lines)
        (out_dir / f"Discharge_Summary_{i+1:03d}_{topic['abbrev']}.txt").write_text(text_content, encoding="utf-8")

    print(f"Generated {count} TXT documents in {out_dir}")


def create_backup_duplicates(count: int = 5):
    """Copy sample files to backup folder to test duplicate detection and incremental tracking."""
    out_dir = CORPUS_ROOT / "backup_duplicates"
    src_dir = CORPUS_ROOT / "docx_trials"
    files = list(src_dir.glob("*.docx"))[:count]

    for f in files:
        shutil.copy2(str(f), str(out_dir / f"Duplicate_Copy_of_{f.name}"))

    print(f"Created {len(files)} duplicate test files in {out_dir}")


def create_corrupted_documents(count: int = 5):
    """Create damaged or invalid files to verify graceful error handling."""
    out_dir = CORPUS_ROOT / "corrupted"

    # 1. 0-byte file
    (out_dir / "Corrupted_Empty_ZeroByte.pdf").write_bytes(b"")

    # 2. Truncated DOCX (zip file cut in half)
    (out_dir / "Corrupted_Truncated_Archive.docx").write_bytes(b"PK\x03\x04corrupted docx data without central directory")

    # 3. Invalid PDF header
    (out_dir / "Corrupted_Invalid_Header.pdf").write_bytes(b"THIS IS NOT A PDF FILE HEADER\x00\x01\x02\x03")

    # 4. Truncated PDF missing xref
    (out_dir / "Corrupted_Missing_Xref.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF")

    # 5. Invalid DOC binary
    (out_dir / "Corrupted_Damaged_Legacy.doc").write_bytes(b"\xD0\xCF\x11\xE0corrupted ole2 stream")

    print(f"Created {count} corrupted test files in {out_dir}")


def main():
    print(f"Generating realistic sample corpus in {CORPUS_ROOT}...")
    if CORPUS_ROOT.exists():
        shutil.rmtree(CORPUS_ROOT)

    ensure_dirs()
    create_docx_documents(35)
    create_pdf_documents(35)
    create_legacy_doc_documents(15)
    create_scanned_pdf_documents(15)
    create_mixed_pdf_documents(10)
    create_hindi_documents(10)
    create_txt_documents(10)
    create_backup_duplicates(5)
    create_corrupted_documents(5)

    total_files = len(list(CORPUS_ROOT.rglob("*.*")))
    print(f"\n==================================================")
    print(f"Sample Corpus Generation COMPLETE: {total_files} files created.")
    print(f"==================================================")


if __name__ == "__main__":
    main()
