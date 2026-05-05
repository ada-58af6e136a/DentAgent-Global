# Scenario Map — Dent Agent
**Stack:** Python · LangChain · Claude API · ChromaDB · Streamlit  
**Clients:** USA · France · China · Netherlands · Germany · Spain · Belgium  
**Channel:** Email only (Gmail API / IMAP)  


This file is the source of truth for three things:

1. **`knowledge_base/faq.txt`** — the Q:/A: pairs at the bottom of each scenario are copied directly into this file
2. **`system_prompt.py`** — the escalation rules and hard limits section is copied from the tables below
3. **`classifier.py`** — the intent labels in each scenario header map 1:1 to the labels used in the zero-shot classification prompt

---

## Email system audit

| Field | Detail |
|---|---|
| Email provider | Gmail / Outlook / other |
| API access | Gmail API OAuth confirmed / IMAP enabled  |
| Average daily volume |  30–50 emails per day|
| Peak hours (local time) | 9 am–12 pm GMT |
| Client countries | USA, France, China, Netherlands, Germany, Spain, Belgium |
| Client languages | English, French, Chinese, Dutch, German, Spanish |
| Inbox type | Shared inbox / individual accounts|
| 24-hour coverage needed | Yes |
| Human review mode | Version 1: all drafts reviewed before send. Version 2+: standard intents auto-send |

---

## Escalation rules — hardcoded into system_prompt.py

These situations bypass M4 reply generation entirely. M2 sets `escalate: true` and the email is written to `human_queue.jsonl`. The AI writes an acknowledgement draft only — no resolution, no commitment.

| ID | Situation | Why | Agent action |
|---|---|---|---|
| E1 | Client complaint or strong dissatisfaction | Relationship risk — requires human empathy and authority | Write acknowledgement draft, flag to human queue |
| E2 | Rework or return decision request | Commercial commitment — not AI's call | Write acknowledgement draft, collect case details, flag to human |
| E3 | Billing dispute or invoice disagreement | Financial risk | Collect invoice number and disputed amount, flag to accounts team |
| E4 | Client explicitly requests a manager or senior staff | Human explicitly requested | Write acknowledgement, flag immediately, do not attempt to resolve |
| E5 | Question not answered by knowledge base | Must not fabricate | Reply: "Our specialist team will follow up within 1 business day", flag |
| E6 | Client expresses urgency tied to a patient appointment at risk | Time-critical — requires human judgement on rush approval | Acknowledge urgency, collect appointment date and order reference, flag as urgent |
| E7 | Client threatens legal action, regulatory complaint, or formal dispute | Legal and reputational risk | Write neutral acknowledgement only, flag to management immediately, do not engage with the threat |
| E8 | Client requests a custom pricing arrangement or volume discount negotiation | Commercial negotiation — not AI's call | Acknowledge request, say a team member will be in touch, flag to sales |
| E9 | Client reports a patient adverse event or clinical complication | Regulatory and liability risk | Write neutral acknowledgement, collect case details, flag to quality team and management immediately |
| E10 | Client asks for information that would require accessing patient records or clinical data | Privacy and compliance | Decline politely, explain that patient data requests must be handled by a staff member |

**Hard limits — system_prompt.py:**

```
1. Never invent a price. Only quote prices explicitly documented in the knowledge base.
2. Never commit to a delivery date outside the standard lead times in order_process.txt.
3. Never diagnose a patient's clinical condition or override a dentist's treatment plan.
4. If the answer is not in the knowledge base, say: "Our specialist team will review your enquiry and respond within 1 business day." Do not guess.
5. If the email contains a complaint, rework request, billing dispute, or the client asks to speak with a manager, set escalate: true and generate an acknowledgement only.
6. Always reply in the same language as the incoming email. Detect language from the email body, not the sender's country.
```

---

## Intent label reference — match classifier.py

| Label | Scenario | Auto-reply | Escalate | M6 called |
|---|---|---|---|---|
| `PRICING` | Pricing query | Yes | No | No |
| `MATERIAL` | Material recommendation | Yes | No | No |
| `PROGRESS` | Order progress | Yes | No | Yes |
| `TECHNICAL` | Technical anomaly / design issue | Yes (simple) / flag (complex) | Complex only | No |
| `REWORK` | Rework or after-sales | Acknowledgement only | Always | No |
| `BILLING` | Billing and account reconciliation | Simple requests only | Disputes always | No |
| `OTHER` | Unclassified | No | Yes | No |

---

## Scenario 1 — Pricing Query

**Intent label:** `PRICING`  
**Estimated frequency:** ~15 emails/day   
**Most common languages:** English, French  
**Module path:** M1 → M2 → M3 → M4 → review gate → M1 send → M7 log  
**Escalate:** No

### Triggers — phrases that activate this intent

Direct price requests:
- "How much does a [product] cost?"
- "What is the price for a [material] crown?"
- "Can you send me your price list?"
- "What is your pricing for zirconia crowns?"
- "How much for [number] units of [product]?"
- "We need a quotation for [material/procedure]."
- "Please quote us for [tooth number] [restoration type]."
- "Can you give me a price estimate for this case?"

Comparison and selection:
- "What is the cost difference between [material A] and [material B]?"
- "Is zirconia more expensive than PFM?"
- "What is the cheapest option for a posterior crown?"
- "We are on a tight budget — what would you recommend?"
- "Which material gives the best value for money?"

Volume and discount:
- "Do you offer discounts for bulk orders?"
- "We place around [number] cases per month — can we get a better rate?"
- "Is there a volume pricing tier?"
- "What is the price if we order 20 units at once?"

Rush and surcharge:
- "How much extra for a 3-day turnaround?"
- "What is the rush fee?"
- "We need this urgently — what are the express costs?"

Shipping and total cost:
- "Does the price include shipping to [country]?"
- "What is the total landed cost to France?"
- "Are there any additional fees we should know about?"

Formal documentation:
- "Can you send a formal quotation?"
- "We need a written quote for our records."
- "Please provide a proforma invoice."
- "Our clinic requires a formal price list for approval."

### Standard process 

1. Retrieve relevant pricing chunks from ChromaDB (M3 queries pricing.txt and faq.txt)
2. Check whether the client has specified sufficient detail: product type, material preference, quantity, tooth position or arch
3. If sufficient detail → quote the price range from the knowledge base directly, include lead time and any applicable conditions (minimum order, rush surcharge)
4. If detail is missing → ask exactly one clarifying question. Do not ask multiple questions at once. Offer to send a formal quotation once details are received.
5. If the client asks for a volume discount or custom pricing arrangement → acknowledge the request and flag to human (E8 escalation) — do not negotiate pricing
6. If the client asks for shipping cost → state that shipping is not included in the listed price and a shipping estimate will be included in the formal quotation
7. Format reply in the client's detected language (M2 output passed to M4)
8. Never quote a price not explicitly documented in pricing.txt
9. Never commit to a price as final — always frame as "approximately" or "starting from" unless a formal quotation has been requested

### Standard reply structure

```
Dear [Dr. / Mr. / Ms. Client Name],

Thank you for your enquiry.

[If sufficient detail:]
Based on the details you have provided, the price for [product description]
using [material brand] is approximately [price range] per unit.
[State any conditions: minimum order quantity, rush surcharge, quote validity period.]

[If detail missing:]
To provide an accurate quotation, could you please confirm:
- [Missing detail 1, e.g. preferred material or material grade]
- [Missing detail 2, e.g. number of units]

We will send a formal quotation within [X] business hours once we have these details.

Please do not hesitate to contact us if you have any further questions.

Best regards,
Customer Service Team
```

### Knowledge base entries → faq.txt

---

## Scenario 2 — Material Recommendation

**Intent label:** `MATERIAL`  
**Estimated frequency:** ~8 emails/day 
**Most common languages:** English, Chinese 
**Module path:** M1 → M2 → M3 → M4 → review gate → M1 send → M7 log  
**Escalate:** No (unless clinical situation is too complex — flag to senior technician)

### Triggers

Recommendation requests:
- "What material do you recommend for [clinical situation]?"
- "Which material is best for this case?"
- "Can you advise on the material choice?"
- "We are not sure which material to use — can you help?"
- "What would you suggest for a patient with [condition]?"

Specific clinical situations:
- "My patient grinds their teeth — what should I use?"
- "This is a bruxism patient — what material do you recommend?"
- "The patient has a high aesthetic demand — what are my options?"
- "This is a molar with heavy occlusal load."
- "We need something for a full arch implant-supported bridge."
- "Patient is allergic to metal — what are the alternatives?"
- "We need a metal-free option."
- "This is an anterior case — aesthetics are the priority."
- "Posterior case, patient has limited budget."

Comparisons:
- "Which is better — zirconia or PFM for [case]?"
- "What is the difference between e.max and zirconia?"
- "Is monolithic zirconia as good as layered?"
- "We have been using PFM — should we switch to zirconia?"
- "What is the advantage of [material] over [material]?"

Suitability questions:
- "Is [material] suitable for posterior teeth?"
- "Can e.max be used for a bridge?"
- "Is zirconia suitable for implant crowns?"
- "We need something aesthetic but also strong for [tooth position]."
- "Is PEEK appropriate for this type of case?"

Shade and appearance:
- "Which material gives the most natural appearance?"
- "We need to match adjacent natural teeth — which material is closest?"
- "What material do you recommend for shade matching?"

### Standard process

1. Identify the clinical situation from the email: tooth position (anterior / posterior), patient condition (bruxism, metal allergy, aesthetic demand, budget constraint), restoration type (single crown, bridge, implant, veneer)
2. Retrieve relevant material chunks from ChromaDB (M3 queries materials.txt and faq.txt)
3. Recommend a primary material with a brief rationale grounded in the retrieved content — state the key reason clearly (e.g. "monolithic zirconia is recommended because of its fracture resistance under heavy bite forces")
4. Mention one alternative if the primary recommendation does not fit the budget or a specific constraint the client mentioned
5. If the email does not provide enough clinical detail to make a reliable recommendation → ask one specific clarifying question (e.g. tooth position, or whether the patient has parafunctional habits)
6. If the situation involves a complex multi-unit case, a patient with multiple contraindications, or a clinical decision that goes beyond material selection → set escalate: true, flag to senior technician
7. Never diagnose patient conditions or make statements about patient health
8. Never override or second-guess the treating dentist's clinical judgment
9. Format reply in the client's detected language


### Standard reply structure

```
Dear [Client Name],

Thank you for your question.

Based on the clinical situation you have described ([brief restatement]),
we would recommend [material name / brand] for the following reasons:
- [Reason 1: e.g. higher fracture resistance for bruxism cases]
- [Reason 2: e.g. metal-free, excellent biocompatibility]

[If there is a relevant alternative:]
An alternative option would be [material B], which may be more suitable if
[condition, e.g. budget is a primary concern / the case involves a full arch].

[If a key detail is missing:]
To give you a more precise recommendation, could you confirm [missing detail,
e.g. tooth position or whether the patient has heavy bite forces]?

Please feel free to send us the full case details and we can advise further.

Best regards,
Customer Service Team
```

### Knowledge base entries →  faq.txt and materials.txt

---

## Scenario 3 — Order Progress

**Intent label:** `PROGRESS`  
**Estimated frequency:**  ~20 emails/day 
**Most common languages:** English, French, Chinese 
**Module path:** M1 → M2 → M3 → M4 + M6 (order status) → review gate → M1 send → M7 log  
**Escalate:** No (unless order is significantly delayed or client is distressed)  
**M6 note:** system_integration.py is called for this intent. Demo phase: returns placeholder text. Phase 4+: returns real order status from Google Sheets or ERP API.

### Triggers

Status requests:
- "What is the status of my order?"
- "Can you give me an update on case [reference]?"
- "Where is my order?"
- "What stage is my case at?"
- "Has production started on our order?"
- "Is the case in the milling stage yet?"

Delivery and timing:
- "When will order [reference] be ready?"
- "When will the case ship?"
- "Can you confirm the expected delivery date?"
- "My patient's appointment is on [date] — will it arrive in time?"
- "We need this by [date] — is that possible?"
- "Has the case shipped yet?"
- "When was the case dispatched?"
- "Can you confirm the tracking number?"

Late or missing orders:
- "I haven't received my shipment yet."
- "The package has not arrived and the expected date has passed."
- "The tracking shows no update for [number] days."
- "We ordered [number] days ago and have heard nothing."
- "Our order is overdue — what is happening?"

Acknowledgement of receipt:
- "Did you receive our impression?"
- "We sent the model last week — have you received it?"
- "Can you confirm you have our STL files?"

### Standard process

1. Extract the order reference number or case description from the email body. If no reference is provided, check the sender's email address against known client accounts.
2. Call M6 (system_integration.py) to query order status — demo phase: returns placeholder text; Phase 4+: returns real production stage, expected completion date, and dispatch status from the order system
3. Retrieve production workflow description from ChromaDB (M3 queries order_process.txt) to provide context around the current stage
4. If on track → confirm the current production stage, expected completion date, and dispatch method. Provide the tracking number if the case has already shipped.
5. If delayed → explain the reason clearly (using language from knowledge base — do not invent reasons), provide a revised ETA, and proactively offer the rush option if available and the delay is significant
6. If the client has a patient appointment at risk → acknowledge the time pressure explicitly. If the case cannot realistically arrive in time, set escalate: true and flag to human to decide on options (rush, alternative arrangement). Do not make commitments about outcomes.
7. If the order reference cannot be found in the system → ask the client to confirm the reference number or the date the case was sent. Do not state that the order is lost.
8. If the client asks for confirmation of impression receipt and it has been more than 2 business days without an acknowledgement → set escalate: true, flag as urgent for the operations team to locate the shipment


### Standard reply structure

```
Dear [Client Name],

Thank you for following up on your order.

[If on track:]
Your order [reference / case description] is currently in the
[production stage, e.g. porcelain application / final polishing] stage.
The expected completion date is [date], and it will be dispatched via
[shipping method] on approximately [dispatch date].
You will receive a tracking number once it has shipped.

[If delayed:]
We would like to inform you that your order [reference] has experienced
a delay due to [reason, e.g. a design revision / material scheduling].
The revised expected completion date is [new date].
We apologise for the inconvenience and are prioritising your case.
[If rush available: We can offer express processing for an additional fee — please confirm if you would like to proceed.]

[If reference unclear:]
Could you please confirm the order reference number or case details
so we can locate your order in our system?

Best regards,
Customer Service Team
```

### Knowledge base entries → faq.txt and order_process.txt

---

## Scenario 4 — Technical Anomaly / Design Issue

**Intent label:** `TECHNICAL`  
**Estimated frequency:**  ~5 emails/day  
**Most common languages:** English, German, French 
**Module path:** M1 → M2 → M3 + M5 (file detection) → M4 → review gate → M1 send → M7 log  
**Escalate:** Simple issues — No. Complex design disputes or quality complaints — Yes.  
**M5 note:** file_parser.py is relevant here. Demo phase: detects attachment and notes receipt in draft. Phase 4+: extracts text from PDF prescriptions via pypdf.

### Triggers

- "The impression we sent is unclear — can you still proceed?"
Impression quality issues:
- "The impression we sent is unclear — can you still proceed?"
- "We think the impression may be damaged in transit."
- "The margin on the impression is not clear."
- "We are not happy with the impression quality — should we redo it?"
- "The impression material tore when we removed it."

Bite registration issues:
- "There is a problem with the bite registration."
- "The bite record we sent may not be accurate."
- "We forgot to include the bite registration."
- "Can you work without a bite record for this case?"

Digital scan and file issues:
- "The STL file we uploaded may have an error."
- "Our scanner had an issue — the file might be incomplete."
- "The scan file is larger than your limit — how should we send it?"
- "We sent the wrong STL file — please disregard and we will resend."
- "The scan is missing the opposing arch."
- "We are not sure if the margin is captured clearly in the scan."

Prescription errors:
- "We made a mistake in the prescription — can it be corrected?"
- "We specified the wrong shade — can you change it?"
- "The tooth number on the form is wrong."
- "We sent the wrong case notes with this impression."
- "Can you update the material — we want to change from zirconia to e.max?"

Design and production corrections:
- "The design does not match what we requested."
- "We are resending a corrected impression — please hold the previous case."
- "Please pause production until we send updated instructions."
- "We need to change the design before you start milling."
- "The occlusion design we discussed is not reflected in the prescription."

### Standard process

1. Identify the specific nature of the technical issue: impression quality, bite registration missing or inaccurate, STL file problem, prescription error, design mismatch, or instruction to pause production
2. Retrieve relevant technical guidance from ChromaDB (M3 queries order_process.txt and faq.txt)
3. If M5 detects an attachment in the email → acknowledge receipt explicitly in the reply, state that the team will review it
4. Assess whether production can proceed as-is, should be paused, or requires a new submission
5. If resolvable internally without client action → inform the client of what the team will do and any resulting lead time impact. Do not ask the client to do anything unless necessary.
6. If a new impression, corrected file, or updated prescription is required → give the client exactly one clear instruction: what to send, in what format, and where. Do not list multiple alternative options in the same reply.
7. If the client asks to pause production → confirm that production has been paused (or that the instruction has been passed to the production team if demo phase) and provide the reference number. Do not promise specific outcomes.
8. If the issue is a design dispute (the finished or in-progress design does not match what was requested) → set escalate: true, flag to senior technician or production manager
9. For prescription errors discovered after production has started → assess impact based on stage. If beyond the point of correction without a remake, flag to human to communicate with the client.

### Standard reply structure

```
Dear [Client Name],

Thank you for bringing this to our attention.

[If proceeding with internal adjustment:]
Our technical team has reviewed the [impression / file / prescription].
We are able to proceed with the following adjustment: [description].
Please note this may affect the lead time by [X] business days.
The revised expected completion date is [date].

[If new submission required:]
After reviewing the materials you sent, we have identified the following issue:
[specific description].

To proceed, we will need you to resend:
- [Specific item, e.g. a new upper arch impression using [technique]]
- [Any additional requirement]

Once we receive the corrected materials, production will begin immediately
and we estimate a lead time of [X] business days from receipt.

[If attachment detected by M5:]
We have also received your attached [STL file / prescription / design image]
and our team will review it alongside the case.

Please contact us if you need any guidance.

Best regards,
Customer Service Team
```

### Knowledge base entries → faq.txt

---

## Scenario 5 — Rework / After-sales

**Intent label:** `REWORK`  
**Estimated frequency:** ~3 emails/day
**Most common languages:** English, French, Chinese
**Module path:** M1 → M2 → escalation gate → human_queue.jsonl + acknowledgement draft → M7 log  
**Escalate:** Always — without exception.

> **Critical constraint from system_prompt.py hard limits:**  
> The agent must never commit to free rework, paid rework, a refund, or any resolution.  
> Its only permitted action is to acknowledge receipt, collect required case information, and flag to human_queue.jsonl.  
> All resolution decisions are made by a human CS person.

### Triggers

Fit issues:
- "The crown does not fit properly."
- "The restoration does not seat fully."
- "There is an open margin on the crown."
- "The bridge does not fit on both abutments."
- "There is a gap between the crown and the tooth."
- "The crown rocks when seated."
- "We cannot get it to seat — the contact is too tight."

Structural issues:
- "There is a chip in the porcelain."
- "The porcelain has fractured."
- "The crown cracked."
- "The veneer broke during try-in."
- "The appliance broke after [number] days."
- "The clasp on the partial denture snapped."

Aesthetic issues:
- "The shade does not match what we ordered."
- "The colour is completely wrong."
- "It is too dark / too light / too grey."
- "The translucency does not match the adjacent teeth."
- "The shape is not what we designed."

Patient satisfaction:
- "My patient is unhappy with the restoration."
- "The patient is refusing to accept it."
- "The patient says it does not look natural."
- "We need this redone."
- "We cannot deliver this to the patient in its current state."

Return and remake requests:
- "We would like to return this case."
- "Can you remake this?"
- "We need a replacement."
- "This is not acceptable and needs to be redone."
- "The quality is not what we expected."

### Standard process (agent scope — acknowledgement only)

1. M2 classifies as REWORK → sets escalate: true
2. Agent writes acknowledgement draft only — does NOT generate a resolution or quote policy
3. Acknowledgement collects: order reference, description of issue, photos if available
4. Email written to human_queue.jsonl
5. Human CS person reviews, decides on resolution, sends response
6. M7 logs interaction including human edit and final reply

### Acknowledgement draft (agent output — no resolution committed)

```
Dear [Client Name],

Thank you for contacting us regarding your recent order.

We are sorry to hear that the restoration did not meet your expectations.
We take all quality feedback seriously and will review your case as a priority.

To help us investigate, could you please provide:
- Your order reference number
- A brief description of the issue (fit / shade / chip / fracture / other)
- Photographs of the issue if possible

Once we have this information, our quality team will review the case and
respond to you within [X] business hours with a proposed resolution.

We appreciate your patience and look forward to resolving this for you.

Best regards,
Customer Service Team
```

### Knowledge base entries → faq.txt

---

## Scenario 6 — Billing and Account Reconciliation

**Intent label:** `BILLING`  
**Estimated frequency:**  ~2 emails/day, higher at month end  
**Most common languages:** English, French 
**Module path:** M1 → M2 → M3 → M4 (simple requests) or escalation gate (disputes) → M7 log  
**Escalate:** Billing disputes always. Simple document requests — No.

> **Constraint:** The agent can respond to simple document requests (invoice copy, monthly statement).  
> It cannot resolve discrepancies, approve adjustments, or discuss payment terms changes.  
> Those always go to a human.

### Triggers

Account reconciliation:
- "We need to reconcile our account for this month."
- "Can you send us the processing list for [month]?"
- "We need a summary of all orders placed in [month]."
- "Can you confirm the total amount billed this month?"
- "We are doing our end-of-month accounts."

Invoice queries:
- "I have a question about invoice number [number]."
- "Can you resend invoice [number]?"
- "We have not received an invoice for [month]."
- "Can you send the invoice for our last order?"
- "We need a VAT invoice / tax invoice for this order."

Invoice disputes:
- "The amount on the invoice does not match our records."
- "We were charged for [number] units but we only ordered [number]."
- "The price on the invoice is different from the quotation."
- "There is a duplicate charge on this invoice."
- "We should have received a volume discount — it is not reflected."
- "We were charged for a rush order we did not request."

Payment and terms:
- "When is our next payment due?"
- "We would like to update our payment terms."
- "Can we extend our credit period?"
- "We would like to set up a prepaid account."
- "How do we make a payment?"
- "We have made a payment — please confirm receipt."

Account administration:
- "We need to update our billing address."
- "Our company name has changed — please update your records."
- "Can you add a new contact for invoices?"
- "We would like invoices to go to a different email address."

### Standard process

1. Classify request type: document copy / reconciliation / dispute / payment terms change
2. Document copy or statement request → retrieve relevant info, confirm it will be sent within [X] hours
3. Discrepancy or dispute → set escalate: true, write acknowledgement draft, flag to accounts team
4. Payment terms change → set escalate: true, flag to management

### Standard reply structure

```
Dear [Client Name],

Thank you for your message regarding your account.

[If document copy request:]
We will send you a copy of your [invoice / monthly processing list]
for [period] within [X] business hours.

[If discrepancy reported:]
Thank you for flagging this. We have passed the details to our accounts
team who will review and respond to you within [X] business hours.
Could you please confirm the invoice number and the specific amount
in question so we can investigate promptly?

[If payment terms change:]
Thank you for your request. Our accounts manager will be in touch
within [X] business days to discuss this with you directly.

Best regards,
Customer Service Team
```

### Knowledge base entries → faq.txt


---

## Phase alignment — where this document feeds into the codebase

| Phase | How scenario_map.md is used |
|---|---|
| Phase 1 (complete) | Written and committed. Defines scope of knowledge base and escalation rules. |
| Phase 2 (current) | faq.txt Q:/A: entries extracted and added to knowledge_base/faq.txt. Retrieval tested against trigger phrases from each scenario. |
| Phase 3 — demo | classifier.py intent labels verified against the 7 labels in this document. system_prompt.py hard limits section copied verbatim from above. |
| Phase 4 — V1 live | BILLING and TECHNICAL escalation rules reviewed against real email data. Trigger phrase list expanded from interaction_log.jsonl (M7). |
| Phase 5 — V2 auto | Scenario coverage gaps identified from M7 analytics → new Q:/A: pairs added to faq.txt → build_kb.py re-run with reset=True. |

---

## Completion checklist (other things)

- [ ] Escalation rules E1–E7 reviewed and approved by CS team lead
- [ ] At least 10 real historical client emails filed as test cases in docs/test_emails/
- [ ] Intent labels (PRICING, MATERIAL, PROGRESS, TECHNICAL, REWORK, BILLING, OTHER) match exactly what is coded in classifier.py
- [ ] build_kb.py re-run after faq.txt update

---
