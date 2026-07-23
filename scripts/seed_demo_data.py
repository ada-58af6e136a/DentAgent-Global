"""
scripts/seed_demo_data.py

Populates data/drafts.db with a small set of original, clearly-fictional
dental clinic inquiries — spanning every intent, several languages, and
every status the pipeline produces — so a demo deployment shows the full
range of what the system does instead of an empty dashboard.

None of this is derived from real interaction data. Clinic names, emails,
and message content are invented for this script.

Run from the project root:
    python scripts/seed_demo_data.py
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.db import save_draft

random.seed(42)  # reproducible demo data across runs

now = datetime.now(timezone.utc)


def _ts(days_ago: float) -> str:
    return (now - timedelta(days=days_ago)).isoformat()


DEMO_DRAFTS = [
    dict(
        message_id="<demo-001@dentagent-demo>", days_ago=9.4,
        sender="Riverside Dental Lab <orders@riversidedentallab.example>",
        subject="Pricing for full-ceramic zirconia crowns",
        body="Hi, could you send us the current price list for full-ceramic zirconia crowns? We have a batch of 12 coming up.",
        intent="PRICING", language="en", escalate=False, confidence=0.94,
        draft_reply="Dear Riverside Dental Lab team,\n\n"
                    "Thank you for reaching out. Our full-ceramic zirconia crowns are priced at $X per unit for standard shading, "
                    "with volume pricing available for batches of 10+. I've attached our current price list for reference.\n\n"
                    "Please let us know if you'd like to proceed with the order or have any further questions.\n\n"
                    "Best regards,\nCustomer Service Team",
        sources=["pricing.txt"], retrieval_score=0.87,
        status="approved", final_reply=None, human_edited=False,
        prompt_tokens=310, output_tokens=95, total_tokens=405, cost_usd=0.000335,
        used_fallback=False, would_auto_send=True,
    ),
    dict(
        message_id="<demo-002@dentagent-demo>", days_ago=8.7,
        sender="Clinique Dentaire Lumière <contact@cliniquelumiere.example>",
        subject="Recommandation de matériau pour bruxisme",
        body="Quel matériau recommandez-vous pour une couronne antérieure chez un patient bruxeur ?",
        intent="MATERIAL", language="fr", escalate=False, confidence=0.91,
        draft_reply="Bonjour,\n\n"
                    "Merci pour votre question. Pour un patient bruxeur, nous recommandons généralement une couronne en "
                    "zircone monolithique pour sa résistance supérieure à la fracture.\n\n"
                    "N'hésitez pas à nous contacter pour toute question complémentaire.\n\n"
                    "Cordialement,\nL'équipe du service client",
        sources=["materials.txt", "tech_selection.md"], retrieval_score=0.82,
        status="approved", final_reply=None, human_edited=False,
        prompt_tokens=280, output_tokens=88, total_tokens=368, cost_usd=0.000304,
        used_fallback=False, would_auto_send=True,
    ),
    dict(
        message_id="<demo-003@dentagent-demo>", days_ago=8.1,
        sender="阳光口腔诊所 <service@sunshine-dental.example>",
        subject="订单进度查询 - Order #4521",
        body="你好，想咨询一下订单 #4521 目前的生产进度，谢谢。",
        intent="PROGRESS", language="zh", escalate=False, confidence=0.96,
        draft_reply="您好，\n\n"
                    "感谢您的咨询。订单 #4521 目前正在生产中，预计还需 3-4 个工作日完成，我们会在发货后第一时间通知您。\n\n"
                    "如有其他问题，欢迎随时联系我们。\n\n"
                    "此致\n客服团队",
        sources=["order_process.txt"], retrieval_score=0.90,
        status="auto_sent", final_reply=None, human_edited=False,
        prompt_tokens=245, output_tokens=70, total_tokens=315, cost_usd=0.000249,
        used_fallback=False, would_auto_send=True,
    ),
    dict(
        message_id="<demo-004@dentagent-demo>", days_ago=7.5,
        sender="Pinecrest Family Dentistry <lab@pinecrestdental.example>",
        subject="Shade matching question for anterior bridge",
        body="We're having trouble getting an exact shade match on a 3-unit anterior bridge case — any guidance on your process?",
        intent="TECHNICAL", language="en", escalate=False, confidence=0.85,
        draft_reply="Dear Pinecrest Family Dentistry team,\n\n"
                    "Great question — for anterior bridge cases we recommend submitting a digital shade photo under natural "
                    "light alongside the physical shade tab for our technicians to cross-reference.\n\n"
                    "Feel free to send the photo over and we'll take a look right away.\n\n"
                    "Best regards,\nCustomer Service Team",
        sources=["tech_selection.md"], retrieval_score=0.71,
        status="pending_review", final_reply=None, human_edited=False,
        prompt_tokens=390, output_tokens=110, total_tokens=500, cost_usd=0.000392,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-005@dentagent-demo>", days_ago=6.9,
        sender="Maple Street Dental <billing@maplestreetdental.example>",
        subject="Crown does not fit — needs remake",
        body="The crown we received for case #3391 does not seat properly on the prep. We need this remade urgently.",
        intent="REWORK", language="en", escalate=True, confidence=0.60,
        draft_reply="Thank you for your message. Our specialist team will review your enquiry and follow up within 1 business day.",
        sources=[], retrieval_score=0.0,
        status="escalated", final_reply=None, human_edited=False,
        prompt_tokens=180, output_tokens=40, total_tokens=220, cost_usd=0.000154,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-006@dentagent-demo>", days_ago=6.3,
        sender="Zahnklinik am Park <buchhaltung@zahnklinik-park.example>",
        subject="Rechnung Nr. 2291 - Frage zur Zahlung",
        body="Wir haben eine Frage zu Rechnung Nr. 2291 — der Betrag scheint nicht mit unserer Bestellung übereinzustimmen.",
        intent="BILLING", language="de", escalate=True, confidence=0.55,
        draft_reply="Vielen Dank für Ihre Nachricht. Unser Fachteam wird Ihre Anfrage prüfen und sich innerhalb eines "
                    "Werktages bei Ihnen melden.",
        sources=[], retrieval_score=0.0,
        status="escalated", final_reply=None, human_edited=False,
        prompt_tokens=165, output_tokens=38, total_tokens=203, cost_usd=0.000141,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-007@dentagent-demo>", days_ago=5.8,
        sender="Clínica Dental Esperanza <info@dentalesperanza.example>",
        subject="Precio de coronas de disilicato de litio",
        body="¿Podrían indicarnos el precio actual de las coronas de disilicato de litio para dientes posteriores?",
        intent="PRICING", language="es", escalate=False, confidence=0.88,
        draft_reply="Estimado equipo de Clínica Dental Esperanza,\n\n"
                    "Gracias por su consulta. El precio de nuestras coronas de disilicato de litio para dientes "
                    "posteriores es de $X por unidad, con descuentos disponibles para pedidos de mayor volumen.\n\n"
                    "Quedamos a su disposición para cualquier consulta adicional.\n\n"
                    "Saludos cordiales,\nEquipo de Atención al Cliente",
        sources=["pricing.txt"], retrieval_score=0.68,
        status="pending_review", final_reply=None, human_edited=False,
        prompt_tokens=300, output_tokens=92, total_tokens=392, cost_usd=0.000319,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-008@dentagent-demo>", days_ago=5.2,
        sender="Golden Gate Dental Studio <orders@ggdentalstudio.example>",
        subject="Zirconia vs e.max for molar crown",
        body="For a molar crown on a heavy grinder, would you recommend zirconia or e.max? Trying to decide before we submit the case.",
        intent="MATERIAL", language="en", escalate=False, confidence=0.93,
        draft_reply="Dear Golden Gate Dental Studio team,\n\n"
                    "For a heavy grinder on a molar, we'd recommend monolithic zirconia over e.max — it offers "
                    "significantly better fracture resistance under high occlusal load.\n\n"
                    "Let us know if you'd like to move forward with this option for the case.\n\n"
                    "Best regards,\nCustomer Service Team",
        sources=["materials.txt"], retrieval_score=0.79,
        status="approved", final_reply=None, human_edited=False,
        prompt_tokens=295, output_tokens=90, total_tokens=385, cost_usd=0.0000714,  # partly DeepSeek-priced (cheaper)
        used_fallback=True, would_auto_send=True,
    ),
    dict(
        message_id="<demo-009@dentagent-demo>", days_ago=4.6,
        sender="Tandartspraktijk De Wit <planning@dewittandarts.example>",
        subject="Status van bestelling #7734",
        body="Kunt u ons laten weten wat de huidige status is van bestelling #7734?",
        intent="PROGRESS", language="nl", escalate=False, confidence=0.79,
        draft_reply="Beste Tandartspraktijk De Wit,\n\n"
                    "Bedankt voor uw bericht. Bestelling #7734 bevindt zich momenteel in de afwerkingsfase en zou "
                    "over 2-3 werkdagen verzendklaar moeten zijn.\n\n"
                    "Heeft u nog vragen, laat het ons gerust weten.\n\n"
                    "Met vriendelijke groet,\nKlantenserviceteam",
        sources=["order_process.txt"], retrieval_score=0.60,
        status="pending_review", final_reply=None, human_edited=False,
        prompt_tokens=250, output_tokens=75, total_tokens=325, cost_usd=0.000263,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-010@dentagent-demo>", days_ago=4.0,
        sender="美迪牙科中心 <cs@meidi-dental.example>",
        subject="全瓷冠价格咨询",
        body="您好，请问全瓷冠现在的价格是多少？我们打算下个月批量订购。",
        intent="PRICING", language="zh", escalate=False, confidence=0.97,
        draft_reply="您好，\n\n"
                    "感谢您的咨询。全瓷冠目前的标准价格为每颗 $X，如批量订购（10 颗以上）可享受优惠价格，详情请见附件报价单。\n\n"
                    "如需进一步沟通订购细节，欢迎随时联系我们。\n\n"
                    "此致\n客服团队",
        sources=["pricing.txt"], retrieval_score=0.93,
        status="auto_sent", final_reply=None, human_edited=False,
        prompt_tokens=270, output_tokens=80, total_tokens=350, cost_usd=0.000281,
        used_fallback=False, would_auto_send=True,
    ),
    dict(
        message_id="<demo-011@dentagent-demo>", days_ago=3.4,
        sender="Coastal Dental Arts <techsupport@coastaldentalarts.example>",
        subject="Occlusal adjustment guidance for night guard",
        body="Any guidance on occlusal adjustment for a hard night guard on a patient with a deep bite?",
        intent="TECHNICAL", language="en", escalate=False, confidence=0.72,
        draft_reply="Dear Coastal Dental Arts team,\n\n"
                    "For a deep bite case, we generally recommend a slightly thicker guard in the anterior region "
                    "with even contact distribution — happy to review the specific case if you can send the scan.\n\n"
                    "Looking forward to hearing from you.\n\n"
                    "Best regards,\nCustomer Service Team",
        sources=["tech_selection.md"], retrieval_score=0.55,
        status="pending_review", final_reply=None, human_edited=False,
        prompt_tokens=410, output_tokens=120, total_tokens=530, cost_usd=0.000423,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-012@dentagent-demo>", days_ago=2.8,
        sender="Harbor View Dental <admin@harborviewdental.example>",
        subject="Quick question about your lab hours",
        body="What are your customer service hours over the holidays this year?",
        intent="OTHER", language="en", escalate=True, confidence=0.65,
        draft_reply="Thank you for your message. Our specialist team will review your enquiry and follow up within 1 business day.",
        sources=[], retrieval_score=0.0,
        status="escalated", final_reply=None, human_edited=False,
        prompt_tokens=140, output_tokens=35, total_tokens=175, cost_usd=0.000123,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-013@dentagent-demo>", days_ago=2.1,
        sender="Cabinet Dentaire Bellevue <secretariat@dentaire-bellevue.example>",
        subject="Devis pour bridge en zircone",
        body="Pourriez-vous nous envoyer un devis pour un bridge de 3 éléments en zircone ?",
        intent="PRICING", language="fr", escalate=False, confidence=0.89,
        draft_reply="Bonjour,\n\n"
                    "Merci pour votre demande. Pour un bridge de 3 éléments en zircone, le prix est de $X, transport inclus.\n\n"
                    "Cordialement,\nL'équipe du service client",
        sources=["pricing.txt"], retrieval_score=0.74,
        status="edited", final_reply="Bonjour,\n\n"
                                      "Merci pour votre demande. Pour un bridge de 3 éléments en zircone monolithique, "
                                      "le tarif est de $X TTC, livraison sous 10 jours ouvrés incluse.\n\n"
                                      "N'hésitez pas à nous contacter pour toute précision.\n\n"
                                      "Cordialement,\nL'équipe du service client",
        human_edited=True,
        prompt_tokens=305, output_tokens=95, total_tokens=400, cost_usd=0.000330,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-014@dentagent-demo>", days_ago=1.5,
        sender="Northgate Dental Lab <purchasing@northgatedental.example>",
        subject="Material options for allergy-sensitive patient",
        body="We have a patient with a known nickel sensitivity — what crown material options would you suggest?",
        intent="MATERIAL", language="en", escalate=False, confidence=0.81,
        draft_reply="Dear Northgate Dental Lab team,\n\n"
                    "For patients with nickel sensitivity, we'd recommend a metal-free option such as zirconia or "
                    "e.max — both are fully biocompatible and avoid any nickel-containing alloys.\n\n"
                    "Happy to discuss further if you'd like more detail on either option.\n\n"
                    "Best regards,\nCustomer Service Team",
        sources=["materials.txt"], retrieval_score=0.65,
        status="pending_review", final_reply=None, human_edited=False,
        prompt_tokens=285, output_tokens=85, total_tokens=370, cost_usd=0.000297,
        used_fallback=False, would_auto_send=False,
    ),
    dict(
        message_id="<demo-015@dentagent-demo>", days_ago=0.6,
        sender="Willowbrook Dental Group <frontdesk@willowbrookdental.example>",
        subject="Following up on order #8812 status",
        body="Just following up — where does order #8812 stand? We'd like to give the patient an update.",
        intent="PROGRESS", language="en", escalate=False, confidence=0.95,
        draft_reply="Dear Willowbrook Dental Group team,\n\n"
                    "Thanks for checking in — order #8812 has completed quality inspection and is scheduled to ship "
                    "tomorrow. You'll receive a tracking notification once it's on its way.\n\n"
                    "Please let us know if there's anything else we can help with.\n\n"
                    "Best regards,\nCustomer Service Team",
        sources=["order_process.txt"], retrieval_score=0.88,
        status="approved", final_reply=None, human_edited=False,
        prompt_tokens=260, output_tokens=78, total_tokens=338, cost_usd=0.000273,
        used_fallback=False, would_auto_send=True,
    ),
]


def seed() -> int:
    inserted = 0
    for d in DEMO_DRAFTS:
        timestamp = _ts(d["days_ago"])
        entry = {
            "message_id": d["message_id"],
            "timestamp": timestamp,
            "from": d["sender"],
            "subject": d["subject"],
            "body": d["body"],
            "intent": d["intent"],
            "language": d["language"],
            "escalate": d["escalate"],
            "confidence": d["confidence"],
            "draft_reply": d["draft_reply"],
            "sources": d["sources"],
            "retrieval_score": d["retrieval_score"],
            "status": d["status"],
            "final_reply": d.get("final_reply") or d["draft_reply"],
            "human_edited": d.get("human_edited", False),
            "processed_at": timestamp if d["status"] != "pending_review" else None,
            "classify_elapsed": round(random.uniform(0.4, 1.2), 3),
            "rag_elapsed": round(random.uniform(0.8, 2.5), 3) if d["sources"] else 0.0,
            "total_elapsed": round(random.uniform(1.5, 4.0), 3),
            "prompt_tokens": d["prompt_tokens"],
            "output_tokens": d["output_tokens"],
            "total_tokens": d["total_tokens"],
            "estimated_cost_usd": d["cost_usd"],
            "used_fallback": d["used_fallback"],
            "would_auto_send": d["would_auto_send"],
        }
        if save_draft(entry):
            inserted += 1
    return inserted


if __name__ == "__main__":
    count = seed()
    print(f"Seeded {count} demo draft(s) into data/drafts.db "
          f"(already-seeded rows are skipped — safe to re-run).")
