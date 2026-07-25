"""
Shared helpers for sitemap generation.

`is_individual_slug` is a CONSERVATIVE, name-based classifier for individual
practitioners (as opposed to businesses/facilities). It exists because the
`Provider.is_individual` DB column is not reliably populated, yet individual
practitioner pages should not be actively submitted to Google via the sitemaps.

Deliberately conservative: it only flags slugs that end in a professional
credential (…-md, …-od, …-dpm, …-dc, …) or carry a clear "dr" marker, AND that
contain no business signal word. This keeps false positives near zero (a real
business almost never ends in "-md"), at the cost of missing plain-name
individuals with no credential suffix — those are left in and rely on the
provider page's own noindex handling.
"""
import re

# Professional-credential suffixes appended to a person's name.
_CRED = (
    'md', 'do', 'dpm', 'dds', 'dmd', 'od', 'crna', 'np', 'pa-c', 'pac',
    'lcsw', 'phd', 'facs', 'faad', 'dnp', 'msn', 'rn', 'aprn', 'pt', 'dc',
    'dvm', 'edd', 'psyd', 'mph', 'ms', 'lac', 'lmt',
)
_CRED_RE = re.compile(r'-(?:' + '|'.join(map(re.escape, _CRED)) + r')$')
_DR_RE = re.compile(r'(^dr-|-dr$|^doctor-)')

# Any of these substrings means "business/facility" — never strip these.
_BIZ_RE = re.compile(
    r'(inc|llc|pllc|-pc$|-pa$|group|cent(?:er|re)|clinic|assoc|surg|medical|'
    r'health|hospital|spa|aesthetic|dermatolog|orthop|imaging|radiolog|'
    r'institute|partners|special|wellness|care|lab|company|-co$|corp|'
    r'physician|practice|consult|systems?|network|pharmacy|urgent|family|'
    r'pediatric|dental|vision|eye|university|regional|community|county|studio|'
    r'salon|beauty|skin|laser|weight|therapy|rehab|nutrition|braces|smile|'
    r'ortho|clinics|services|solutions|management|holdings|enterprises|'
    r'foundation|academy|college|school|and-|-of-|-the-)'
)


def is_individual_slug(slug):
    """True if a provider slug looks like an individual practitioner (safe to
    drop from the sitemap). Conservative — see module docstring."""
    if not slug:
        return False
    s = slug.lower()
    if _BIZ_RE.search(s):
        return False
    return bool(_CRED_RE.search(s) or _DR_RE.search(s))
