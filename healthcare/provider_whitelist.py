"""
Per-procedure provider-type whitelist (cash-pay pages).

The scraped "Market Estimate" data bulk-assigned procedures to a generic "Clinic"
provider-type bucket, which mixes credible providers with contamination — e.g.
orthodontists ("Wise Braces"), endocrinologists ("Miami Diabetes & Endocrinology"),
and weight/general-surgery clinics showing up on the Botox list. A user who sees
an orthodontist listed for Botox distrusts the whole page.

Fix: only show providers whose provider-type is credible for the procedure. This
is a deliberate PRECISION-over-recall choice — the "Clinic" bucket also contains
some real med spas that were miscategorized, but it cannot be split reliably by
type, so we drop the whole bucket. Credible-typed pools remain far above the
thin-data threshold in real cities.

Edit this mapping to tune coverage. Keys are procedure slugs; values are the
ProviderType.name values allowed for that procedure. A procedure NOT present here
is left unfiltered (no whitelist applied).
"""

# Credible provider types per procedure slug.
PROCEDURE_PROVIDER_TYPE_WHITELIST = {
    # --- Injectables / aesthetics (drop "Clinic" contamination) ---
    'botox-full-face':       ['Med Spa', 'Plastic Surgery Practice', 'Dermatology'],
    'dermal-fillers-lips':   ['Med Spa', 'Plastic Surgery Practice', 'Dermatology'],
    'coolsculpting':         ['Med Spa', 'Plastic Surgery Practice', 'Dermatology'],

    # --- Dental ---
    'dental-crown-porcelain': ['Dental Office'],
    'dental-implant-single':  ['Dental Office'],
    'teeth-whitening':        ['Dental Office'],

    # --- Vision ---
    'lasik-both-eyes': ['Eye Center', 'Hospital'],

    # --- Hair restoration ---
    'fue-hair-transplant': ['Hair Restoration Clinic'],

    # --- Bariatric ---
    'gastric-sleeve': ['Weight Loss Clinic', 'Surgery Center', 'Hospital'],

    # --- Fertility ---
    'ivf-cycle':    ['Fertility Clinic', 'Hospital'],
    'egg-freezing': ['Fertility Clinic', 'Hospital'],
    'iui':          ['Fertility Clinic', 'Hospital'],

    # --- Surgical plastic surgery (currently is_cash_pay_common=FALSE; mapping
    #     is staged here so it's ready when the provider mapping is enabled.
    #     Note: Med Spa is intentionally NOT credible for these surgeries.) ---
    'rhinoplasty':        ['Plastic Surgery Practice', 'Surgery Center', 'Hospital'],
    'liposuction':        ['Plastic Surgery Practice', 'Surgery Center', 'Hospital'],
    'breast-augmentation':['Plastic Surgery Practice', 'Surgery Center', 'Hospital'],
    'blepharoplasty':     ['Plastic Surgery Practice', 'Surgery Center', 'Hospital'],
    'facelift':           ['Plastic Surgery Practice', 'Surgery Center', 'Hospital'],
}


def allowed_provider_types(procedure_slug):
    """Return the list of credible provider-type names for a procedure, or None
    if no whitelist is configured (meaning: do not filter)."""
    return PROCEDURE_PROVIDER_TYPE_WHITELIST.get(procedure_slug)
