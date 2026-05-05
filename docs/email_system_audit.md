# Email System Audit
**Phase 1 — Step 2 deliverable**
Completed by: Li Wei (CS Manager, Chaowei Dental)
Date completed: 2026-04-28

---

## 1. Email Provider

**Which email platform does the company use for client communications?**

- [ ] Gmail (Google Workspace)
- [x] Outlook / Microsoft 365
- [ ] Custom company domain with hosted provider (e.g. Zoho, Fastmail)
- [ ] Other: _______________

**Primary client-facing email address(es):**
```
international@chaowei-dental.com
orders@chaowei-dental.com
```

---

## 2. API / Integration Access

**Is programmatic access available for this inbox?**

| Method | Available? | Notes |
|--------|-----------|-------|
| Gmail API (OAuth 2.0) | No | Not using Gmail |
| Gmail IMAP | No | Not using Gmail |
| Outlook Graph API | Yes | Microsoft 365 Business Standard licence |
| IMAP (generic) | Yes | IMAP enabled on both mailboxes |
| SMTP (for sending) | Yes | Port 587, TLS |

**Is there an IT administrator or person who controls email access permissions?**
Name / contact: Zhang Hao (IT, internal) — ext. 214

**Are there any known restrictions on third-party app access to the inbox?**
No current restrictions. IT confirmed OAuth app registration is allowed under the current M365 tenant settings. Will need IT to register the agent app and grant mailbox read/send permissions before Phase 3.

---

## 3. Email Volume

**Average number of client inquiries received per day:**
35–50 emails (combined across both inboxes)

**Peak days / times (e.g. Monday mornings, end of month):**
Monday and Tuesday mornings (China time) — European clients send end-of-week on Friday their time, which arrives Saturday morning China time and piles up for Monday. End of month sees a 20–30% spike in order status enquiries.

**Primary source countries and their typical send times (local time):**

| Country | Approx. daily volume | Their local business hours |
|---------|---------------------|--------------------------|
| United States | 8–10 emails | 09:00–18:00 EST (UTC-5) |
| France | 6–8 emails | 09:00–18:00 CET (UTC+1) |
| Germany | 5–7 emails | 09:00–18:00 CET (UTC+1) |
| Netherlands | 4–5 emails | 09:00–18:00 CET (UTC+1) |
| Spain / Belgium | 3–4 emails | 09:00–18:00 CET (UTC+1) |
| China (domestic) | 8–12 emails | 09:00–18:00 CST (UTC+8) |
| Other | 2–3 emails | Various |

---

## 4. Current Inbox Organisation

**Are there existing labels, folders, or sorting rules in the inbox?**
- [ ] No — everything lands in one inbox
- [x] Yes — describe below:

Outlook rules currently sort incoming mail into: `Europe/`, `USA/`, `Domestic-CN/`, `Complaints/`, and `Unread-Urgent/`. Rules are based on sender domain and subject keywords. Not consistently maintained — approximately 30% of emails land in the wrong folder.

**Are client emails currently separated from internal emails?**
- [x] Yes (how?): international@chaowei-dental.com is used exclusively for client-facing communication. Internal email runs on a separate @internal.chaowei-dental.com domain.

**Is there an existing ticketing or CRM system linked to the inbox?**
- [x] Yes (name/system): Basic tracking in a shared Excel file updated manually by CS staff. No formal CRM. Orders are tracked in a separate internal ERP system (not currently API-accessible).

---

## 5. Coverage Requirements

**Is 24-hour response coverage required?**
- [x] Yes — clients expect a reply within hours regardless of time zone
- [ ] No — next business day is acceptable for most markets
- [ ] Depends on market (specify): _______________

**What is the current average response time?**
3–5 hours during China business hours. 10–16 hours for emails sent outside China business hours (i.e. European afternoon / US business hours). Some emails go unanswered until the following day.

**What happens to emails that arrive outside business hours right now?**
No coverage. Emails sit unread until CS staff arrive the next morning (09:00 CST). US clients sending at 14:00 EST wait until the following morning China time — roughly a 19-hour gap. This is the primary pain point.

---

## 6. Reply Mode Decision

Based on the above, the agent will operate in:

- [ ] **Draft + human review** — agent writes a draft, a staff member approves before sending
- [ ] **Fully automatic** — agent sends replies directly for high-confidence scenarios
- [x] **Hybrid** — automatic for standard queries (pricing, order status), human review for complaints and edge cases

**Reason for choice:**
Standard pricing and order progress queries have predictable, verifiable answers and low risk. Complaints, rework requests, and billing disputes carry reputational and financial risk — a human must review these before any reply is sent. The hybrid model allows 24h coverage for the majority of emails while keeping humans in the loop for sensitive cases.

---

## 7. Blockers / Open Questions

List anything that needs to be resolved before Phase 3 email integration can begin:

1. IT (Zhang Hao) needs to register the agent application in Azure AD and grant `Mail.Read` and `Mail.Send` permissions on the `international@chaowei-dental.com` mailbox via the Microsoft Graph API.
2. Decision needed on whether the agent replies from the same address (`international@`) or a separate address (e.g. `agent@chaowei-dental.com`) so clients know they may be reading an AI draft.
3. ERP order tracking system is not currently API-accessible — order status queries will need to be answered from the knowledge base only until ERP integration is scoped separately.

---

## Summary

| Item | Answer |
|------|--------|
| Email provider | Microsoft 365 (Outlook) |
| API access confirmed | Pending — IT registration required |
| Daily email volume | 35–50 emails |
| 24h coverage required | Yes |
| Reply mode | Hybrid (auto for standard, human review for complaints) |
| Integration blocker | Yes — Azure AD app registration needed before Phase 3 |
