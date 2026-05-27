# Taxonomy Codes — Future Import Reference

## Currently Importing
- Plastic Surgery (208200000X, 207KA0200X, 2086S0105X)
- Dental (122300000X + variants)
- Ophthalmology/LASIK (207W00000X, 207WX0200X, 152100000X)
- Optometry (152W00000X + variants)
- Dermatology (207N00000X + variants)
- Fertility (207RE0101X, 207VG0400X)
- Orthopedics (207X00000X + variants)
- Weight Loss/Bariatric (207RG0300X)
- Chiropractor (111N00000X + variants)
- Physical Therapy (225100000X, 225101000X)
- Urgent Care (261QU0200X)
- Imaging Center (261QR0200X)
- Surgery Center/ASC (261QA1903X, 261QM0801X)
- Mental Health (103T00000X + variants)
- Podiatry (213E00000X + variants)
- Gastroenterology (207RG0100X)
- Cardiology (207RC0000X + variants)
- OB/GYN (207V00000X + variants)
- Diagnostic Radiology (2085R0202X + variants)
- Urology (208800000X + variants)
- ENT (207Y00000X + variants)
- General Surgery (208600000X + variants)
- Psychiatry (2084P0800X + variants)
- Sleep Medicine (207QS1201X, 2084S0012X)
- Clinical Laboratory (291U00000X, 293D00000X)
- Allergy & Immunology (207K00000X, 207KI0005X)
- Acupuncture (171100000X)
- Audiology (164W00000X, 231H00000X)
- Community Health Center (261QF0400X, 251S00000X)
- Dietitian/Nutrition (133V00000X, 133VN1006X)

## Phase 2 — Add When Ready
Fits the pricing intelligence model but needs dedicated procedure/pricing data first.

### Nurse Practitioners (independent cash-pay)
- 363LF0000X: NP Family (cash-pay clinics, TRT, IV therapy)
- 363LP0200X: NP Pediatrics
- Rationale: NP-run cash clinics are a real market. Import when surfacing walk-in/cash clinic comparisons.

### DME Suppliers
- 332B00000X: DME Supplier (89K providers)
- Rationale: CPAP, hearing aids, wheelchairs, orthotics. Massive markup variance. Add when building equipment pricing layer.

### Skilled Nursing Facilities
- 314000000X: SNF (32K)
- Rationale: $4K-12K/month, families desperately compare. Add when building senior care vertical.

### Assisted Living
- 310400000X: Assisted Living (27K)
- Rationale: Same as SNF. Senior care expansion.

### Home Health
- 251E00000X: Home Health Agency (90K)
- Rationale: $25-75/hour, alternative to facility care. Add with senior care vertical.

### Oncology
- 207RH0003X: Hematology/Oncology
- Rationale: Cancer care pricing is enormous but operationally complex. Institution-grade later vertical.

### Nephrology
- 207RN0300X: Nephrology
- Rationale: Dialysis pricing is huge but longitudinal. Later.

### Pulmonology
- 207RP1001X: Pulmonology
- Rationale: Niche. Later.

### Clinical Psychologist (assessments)
- 103TC0700X: Clinical Psychologist (76K)
- Rationale: ADHD assessments ($1500-5000), neuropsych testing. Episodic, cash-pay, high variance. Strong Phase 2 candidate.

### Pharmacy (specialty only)
- 183500000X: Pharmacist (296K)
- 3336C0003X: Pharmacy (35K)
- Rationale: Don't compete with GoodRx. But compounding pharmacy, infusion centers, specialty meds are Zenthir territory. Later.

## Permanent Skip — Does Not Fit Model
- 207R00000X: Internal Medicine (213K) — directory territory
- 207Q00000X: Family Medicine (199K) — directory territory
- 208000000X: Pediatrics (94K) — too general
- 207P00000X: Emergency Medicine (73K) — no one comparison shops
- 207L00000X: Anesthesiology (68K) — not consumer-selected
- 367500000X: Nurse Anesthetist (68K) — not consumer-selected
- 363A00000X: Physician Assistant (157K) — bills under physician
- 163W00000X: Registered Nurse (183K) — not independent
- 363AM0700X: Medical Assistant (42K) — not independent
- 106S00000X: Behavioral Health Aide (564K) — not consumer-selected
- 390200000X: Student/Trainee (360K) — not practicing
- 104100000X: Social Worker (145K) — not procedure-based
- 207ZP0102X: Pathology — not consumer-selected
- 343900000X: Non-Emergency Transport — different market
- 374U00000X: Health Info Tech — not clinical
- 3747P1801X: Technician — not independent
- 172V00000X: Community Health Worker — not provider
