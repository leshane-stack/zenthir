"""Price basis: what a PricingRecord.cash_price actually represents.

`price_category` is the model default (`submitted_charge`) on all 40.3M rows and
carries no information — a BCBS negotiated rate reads `submitted_charge` today,
which is what let the median blend gross charges with negotiated rates. This
module maps `source_name` (the only field that encodes basis) to an explicit
basis, populated into PricingRecord.price_basis at import and by the backfill.

Aggregations must filter on price_basis, NOT on a startswith against source_name.

Bases:
  submitted_charge  gross / billed charge (what provider pages render)
  negotiated_rate   insurer-negotiated rate (BCBS/UHC/hospital-payer)
  cash_rate         hospital-published discounted cash price (real cash-pay)
  medicare_allowed  a Medicare allowed/payment amount stored as the price
                    (none today: the Medicare allowed lives in insured_price)
  min / max         hospital MRF min / max extremes (not a real transactable price)
  fabricated        synthetic seed data (random.randint), incl. imitation names
"""
SUBMITTED_CHARGE = 'submitted_charge'
NEGOTIATED_RATE = 'negotiated_rate'
CASH_RATE = 'cash_rate'
MEDICARE_ALLOWED = 'medicare_allowed'
MIN = 'min'
MAX = 'max'
FABRICATED = 'fabricated'

BASIS_CHOICES = [
    (SUBMITTED_CHARGE, 'Submitted / gross charge'),
    (NEGOTIATED_RATE, 'Insurer-negotiated rate'),
    (CASH_RATE, 'Hospital cash price'),
    (MEDICARE_ALLOWED, 'Medicare allowed amount'),
    (MIN, 'Hospital MRF minimum'),
    (MAX, 'Hospital MRF maximum'),
    (FABRICATED, 'Fabricated / synthetic'),
]

# source_name prefix -> basis. Order does not matter: no prefix is a proper
# prefix of another that maps to a different basis. ('Market Estimate' prefixes
# 'Market Estimate — Provider can update…', both fabricated.)
BASIS_PREFIXES = (
    ('CMS Medicare Physician Data', SUBMITTED_CHARGE),
    ('CMS Medicare Provider Charge Data', SUBMITTED_CHARGE),
    ('Hospital Chargemaster (Gross)', SUBMITTED_CHARGE),
    ('BCBS Negotiated Rate', NEGOTIATED_RATE),
    ('UHC Negotiated Rate', NEGOTIATED_RATE),
    ('Hospital Negotiated (', NEGOTIATED_RATE),
    ('Hospital Rate (cash)', CASH_RATE),
    ('Hospital Min Rate', MIN),
    ('Hospital Max Rate', MAX),
    ('Market Estimate', FABRICATED),
    ('CMS Price Transparency', FABRICATED),
    ('Aggregated Estimate', FABRICATED),
    ('Provider Website', FABRICATED),
)


def basis_for(source_name):
    """Return the price_basis for a source_name, or None if it maps to nothing
    (an unmapped/new source that must be classified before it is trusted)."""
    if not source_name:
        return None
    for prefix, basis in BASIS_PREFIXES:
        if source_name.startswith(prefix):
            return basis
    return None
