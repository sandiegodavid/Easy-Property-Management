# Property Management App: Pilot Interview Script and Offer

Purpose: find out whether independent property managers (about 10–50 doors, managing for owners) will pay for the workflow in the current MVP, before building payments, portals, or a hosted version.

Everything marked **[hypothesis]** is a starting point to test, not a recommendation.

---

## 1. Who to recruit

Aim for 8–12 interviews, then pick 5–10 for paid pilots.

**Must have**
- Manages roughly 10–50 rentable spaces (single-family, condo, townhome, or small office).
- Manages at least some properties for other owners, not only their own.
- Currently uses spreadsheets, QuickBooks, or a mix. Has real accounting or property-management experience.

**Good to include (a few of each)**
- Someone who tried Buildium, DoorLoop, TenantCloud, or similar and left.
- Someone who has never used property software.
- A mixed owned/managed portfolio.

**Skip for now:** anyone running apartment buildings, or anyone who needs online rent collection to consider switching. You'll learn about them in the interview, but they aren't pilot candidates for this MVP.

**Where to find them:** local landlord and REIA groups, small-PM Facebook and Reddit groups, your own network, referrals from accountants and bookkeepers who serve landlords.

---

## 2. Outreach message

> Hi [Name], I'm building a simple tool for independent property managers who juggle rent, repairs, and owner reporting from spreadsheets and email. I'm not selling anything yet. I'd like 30 minutes to hear how you run things today and get your reaction to an early design. Happy to send a thank-you [gift card / coffee] for your time. Would [day/time] work?

---

## 3. Interview script (30–40 minutes)

**Ground rules**
- Ask about what they *did*, not what they *would* do. Past behavior is more honest than predictions.
- Don't pitch until section D. Stay quiet after questions; let them fill the silence.
- Take notes on exact words they use (they'll become your product language).

### A. Intro (2 min)
"Thanks for making time. I'm exploring how small managers run their day-to-day. There are no right answers, and I'm not selling anything today. Is it okay if I take notes?"

### B. Current workflow (10 min)
1. Walk me through last Monday. What did you actually do for your properties?
2. When something goes wrong, like a repair request or a late payment, how do you find out? Where does it land (text, email, phone, voicemail)?
3. Tell me about the last repair you handled from first message to done. Who did what, and where did you keep track?
4. How do you keep track of what's waiting on someone else (a plumber's quote, a tenant's reply)?
5. What's the thing that most often slips through the cracks?

### C. Money and owners (8 min)
6. How do you collect rent today? Checks, bank transfer, Zelle, a portal? How many of your tenants pay each way?
7. When an owner pays you directly or a tenant pays the owner, how do you find out and record it?
8. Tell me about the last time you sent an owner a statement. How long did it take?
9. How do you handle owners' money between collecting it and paying them? (Listen for: trust account, separate account, mixed. Note the state.)
10. Who does your books, and what do they need from you?

### D. Tools and switching history (5 min)
11. What software, if any, have you tried? What made you start and what made you stop?
12. What do you pay for tools today, in total per month?
13. What would make you *refuse* to switch, even if the new tool were free?

### E. Concept reaction (8 min)
Show the design preview (operator-experience.html) on screen share. Let them click around before explaining.

14. What do you think you're looking at? What would you do first?
15. Which part, if any, would you use every day? Which part would you ignore?
16. Home shows "Needs action / Waiting / Upcoming." How does that compare to how you track things now?
17. The AI issue intake reads messages from email or text and drafts a repair record for you to approve. Where would that help, and where would it worry you?
18. This version runs on one computer and has no tenant portal, no online rent collection, and no automatic messages. What does that do to your interest, honestly?
19. If you were away from your desk, what would you need to see on your phone?

### F. Money talk (4 min)
20. If this saved you [X hours] a week, what would be a fair price per month? At what price would it feel too expensive? At what price would you doubt it works?
21. Would you pay a one-time setup fee to have it set up and your data imported for you?

### G. Close (2 min)
"Would you be open to a paid 60-day pilot with hands-on setup from me? I'd import your properties and keep in touch weekly. Who else should I talk to?"

---

## 4. What to look for (scorecard)

Fill this in after each interview.

| Question | Signal to record |
|---|---|
| Real, recurring pain? | Specific recent story vs. vague complaint |
| Owner money handling | Trust account? State? Owner statements per month? |
| Rent collection dependency | Would they switch without online payments? |
| Desktop-only tolerance | Deal-breaker, tolerable, or fine? |
| Price reaction | Number they gave, and how they reacted to yours |
| AI intake | Excited / cautious / against, and why |
| Pilot commitment | Yes / maybe / no, and what they asked for first |

**Suggested decision rule [hypothesis]:** proceed to pilots only if at least 4 of 10 interviewees describe a recent painful workflow you address, and at least 2–3 say yes to a paid pilot. If most say "I'd need online payments first," pause the local MVP and scope payments-partner integration and a hosted version before selling further.

---

## 5. Pilot offer

### What the customer gets
- A 60-day pilot on their own computer (Mac or Windows [confirm supported platforms]).
- You set up their workspace, import their properties, owners, and service providers from Excel or Google Sheets, and connect their email or SMS source for issue intake if they want it.
- Weekly 20-minute check-in.
- A backup and restore walkthrough, and a first backup verified before go-live.
- Direct line to you for problems (define response time, e.g. one business day).

### What's not included (say this plainly up front)
- Online rent collection, tenant or owner portals, e-signature, tenant screening, bank feeds, and automated sending of messages.
- Trust accounting or bank movement of owner funds. The app records approved disbursements; the customer moves the money.
- Legal advice. Notice, eviction, and rent-rule alerts are planning aids.
- Access from another device. It runs on one computer.

### Proposed terms **[hypothesis, test these]**
- **Setup fee:** a one-time amount that covers your time, for example a few hundred dollars. Charging something matters: it filters for people who will actually use it.
- **Monthly pilot fee:** start with something in the range incumbents charge for entry plans ($60–$70/month is where Buildium and DoorLoop start), or discount it for the pilot period. Ask your interviewees what they'd pay before setting it.
- **Cancel any time.** Refund the setup fee if they leave within 14 days.
- **Their data stays theirs.** They can export everything in a portable format at any point.

### Data and privacy commitments to state
- Records live in a folder on the customer's computer, not on your servers.
- Backups are the customer's responsibility until a hosted version exists. You verify the first one with them.
- Email, SMS, and AI provider credentials stay on their machine and must be re-authorized after a restore.
- If AI features use a cloud provider, tell them exactly what text is sent and get their consent before turning it on.

### Success criteria (agree these on day one)
Pick 3–4 measurable outcomes the customer cares about, for example:
- Fewer items falling through the cracks (they count missed follow-ups before and after).
- Time to send an owner statement.
- Time from a repair report to an assigned provider.
- Whether they still open the app daily by week 4.

### Exit interview at day 60
- Did you use it weekly? Which screens?
- What did you go back to spreadsheets for?
- What's the one missing thing that would stop you from continuing?
- Would you pay to continue at [price]? Would you refer someone?

---

## 6. One-paragraph pilot pitch (for email or a call)

> I'm running a small 60-day pilot of a property management tool built for independent managers who run properties for owners. It gives you one screen for what needs your attention today: overdue rent, repairs waiting on a plumber, owner follow-ups. It can draft repair records from your email and texts for you to approve. I'd set it up on your computer, import your property list, and check in weekly. It doesn't collect rent online yet, so it's not a fit if that's essential. There's a small setup fee and a monthly price you can cancel at any time. Interested in a 30-minute conversation to see if it fits?

---

## 7. Before you start selling

- **Check the trust-accounting rules** in the states where your pilot customers operate. Many states regulate how managers hold client funds. Talk to a lawyer or licensed professional; nothing here is legal advice.
- **Confirm you can support what you install.** Local setup, backups, and the on-device AI option all create support work per customer.
- **Decide what you'll say about AI.** Keep the approach in the brief: AI drafts, the operator approves, nothing is sent or committed automatically.
