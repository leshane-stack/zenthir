"""
Procedure grouping for apples-to-apples comparisons.
When a user enters "MRI brain without contrast" and we have no facility data,
we expand to all MRI brain variants to get a valid comparison set.
"""
from django.db.models import Q


# Maps group name -> Q filter to find all related procedures
PROCEDURE_GROUPS = {
    'mri_brain': Q(name__icontains='mri') & Q(name__icontains='brain') & ~Q(name__icontains='functional') & ~Q(name__icontains='biopsy') & ~Q(name__icontains='destruction') & ~Q(name__icontains='during brain') & ~Q(name__icontains='biochemical') & ~Q(name__icontains='quantitative'),
    'mri_knee': Q(name__icontains='mri') & (Q(name__icontains='knee') | Q(name__icontains='leg joint')),
    'mri_lumbar': Q(name__icontains='mri') & (Q(name__icontains='lumbar') | Q(name__icontains='lower spinal')),
    'mri_shoulder': Q(name__icontains='mri') & (Q(name__icontains='shoulder') | Q(name__icontains='arm joint')),
    'ct_head': Q(name__icontains='ct scan') & (Q(name__icontains='head') | Q(name__icontains='brain')) & ~Q(name__icontains='blood vessels'),
    'ct_abdomen': Q(name__icontains='ct scan') & Q(name__icontains='abdomen') & ~Q(name__icontains='blood vessels'),
    'colonoscopy': Q(name__icontains='colonoscopy') & ~Q(name__icontains='screening'),
    'mammogram': Q(name__icontains='mammogra'),
    'ultrasound_abdominal': Q(name__icontains='ultrasound') & Q(name__icontains='abdom'),
    'xray_chest': Q(name__icontains='x-ray') & Q(name__icontains='chest'),
    'xray_lumbar': Q(name__icontains='x-ray') & (Q(name__icontains='lumbar') | Q(name__icontains='lower') & Q(name__icontains='spine')),
    'ecg': Q(name__icontains='electrocardiogram') & Q(name__icontains='12'),
    'office_visit_established': Q(name__icontains='established') & Q(name__icontains='outpatient') & ~Q(name__icontains='new'),
    'office_visit_new': Q(name__icontains='new patient') & Q(name__icontains='outpatient'),
    'psychotherapy': Q(name__icontains='psychotherapy') & ~Q(name__icontains='family') & ~Q(name__icontains='group'),
    'cataract': Q(name__icontains='cataract') & Q(name__icontains='insertion'),
    'blood_count': Q(name__icontains='complete blood'),
    'metabolic_panel': Q(name__icontains='metabolic') & Q(name__icontains='blood'),
}


def get_procedure_group(procedure):
    """
    Given a procedure, return the group name it belongs to, or None.
    """
    from healthcare.models import Procedure
    
    for group_name, q_filter in PROCEDURE_GROUPS.items():
        if Procedure.objects.filter(q_filter, id=procedure.id).exists():
            return group_name
    return None


def get_related_procedure_ids(procedure):
    """
    Given a procedure, return IDs of all procedures in the same group.
    Returns [procedure.id] if no group found.
    """
    from healthcare.models import Procedure
    
    group_name = get_procedure_group(procedure)
    if group_name:
        q_filter = PROCEDURE_GROUPS[group_name]
        return list(Procedure.objects.filter(q_filter).values_list('id', flat=True))
    return [procedure.id]
