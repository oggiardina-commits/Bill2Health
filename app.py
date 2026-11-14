import hashlib
import html
import re
from datetime import date, datetime

import streamlit as st
import pymupdf as fitz

ANALYSIS_SECTIONS = [
    ("🩺 Health Signals", "health_signals"),
    ("🩺 Health Summary", "health_summary"),
    ("⚠️ Potential Health Risks", "potential_health_risks"),
    ("📅 Follow-Up Care Prompts", "possible_missed_follow_up_care"),
    ("🧭 Care Gap Detector", "care_gap_alerts"),
    ("🧾 Billing Review Prompts", "billing_issues"),
    ("💰 High-Cost Charges", "cost_alerts"),
    ("✅ Recommended Actions", "recommended_actions"),
]

HIGH_COST_THRESHOLD = 1000.00
CARE_GAP_THRESHOLD_DAYS = 365
SAMPLE_PATIENT_FINGERPRINT = "fictional-sample-patient-v1"
SAMPLE_PATIENT_TEXT = """Patient Name: Riley Example
Provider Name: Dr. Jordan Sample, MD
Service Date: 01/15/2024
Office visit - follow-up recommended
Diagnosis: Type 2 diabetes mellitus
Lab Test: HbA1c
Medication: Metformin 500 mg
Blood glucose test: $45.00

Service Date: 01/16/2025
Provider Name: Dr. Casey Sample, MD
Mammogram screening: $250.00
Cardiology consultation for cholesterol monitoring
Follow-up recommended: discuss screening results

Service Date: 02/02/2025
Provider Name: Dr. Jordan Sample, MD
Procedure: MRI brain without contrast | $1,450.00
Procedure: MRI brain without contrast | $1,450.00"""

# These patterns identify mentions only; they do not establish a diagnosis or
# prove that a service, risk, or billing error applies to the patient.
KEYWORD_PATTERNS = {
    "diabetes": re.compile(r"\bdiabetes?\b", re.IGNORECASE),
    "insulin": re.compile(r"\binsulin\b", re.IGNORECASE),
    "A1C": re.compile(r"\b(?:A1C|HbA1c)\b", re.IGNORECASE),
    "blood glucose": re.compile(r"\bblood[\s-]+glucose\b", re.IGNORECASE),
    "hypertension": re.compile(r"\bhypertension\b", re.IGNORECASE),
    "cholesterol": re.compile(r"\bcholesterol\b", re.IGNORECASE),
    "cardiology": re.compile(r"\bcardiolog(?:y|ist)\b", re.IGNORECASE),
    "nephrology": re.compile(r"\bnephrolog(?:y|ist)\b", re.IGNORECASE),
    "ophthalmology": re.compile(r"\bophthalmolog(?:y|ist)\b", re.IGNORECASE),
    "mammogram": re.compile(r"\bmammograms?\b", re.IGNORECASE),
    "MRI": re.compile(r"\bMRI\b", re.IGNORECASE),
    "CT": re.compile(r"\bCT(?:\s+scan)?\b", re.IGNORECASE),
    "emergency room": re.compile(
        r"\b(?:emergency\s+room|emergency\s+department|ER\s+visit)\b",
        re.IGNORECASE,
    ),
    "refill": re.compile(r"\brefills?\b", re.IGNORECASE),
    "prescription": re.compile(r"\bprescriptions?\b", re.IGNORECASE),
    "follow-up": re.compile(r"\bfollow[\s-]?up\b", re.IGNORECASE),
}

HEALTH_SIGNAL_GUIDANCE = {
    "diabetes": (
        "Diabetes-related wording can appear in monitoring or billing descriptions; "
        "a mention alone does not establish a condition.",
        "Ask your healthcare provider whether any monitoring or follow-up is appropriate.",
    ),
    "insulin": (
        "Insulin is a medication name; a bill mention does not show how or whether "
        "someone uses it.",
        "Ask the prescribing clinician or pharmacist about medication questions.",
    ),
    "A1C": (
        "HbA1c testing is commonly used to monitor blood-glucose trends over time. "
        "A bill mention does not provide a result or diagnosis.",
        "Ask your healthcare provider whether follow-up monitoring is needed.",
    ),
    "blood glucose": (
        "Blood-glucose wording may refer to a test or service, not a result.",
        "Ask the ordering provider how to access or discuss any test result.",
    ),
    "hypertension": (
        "This term may appear in a service or billing description; the mention alone "
        "does not establish a diagnosis.",
        "Ask your healthcare provider whether any blood-pressure follow-up is appropriate.",
    ),
    "cholesterol": (
        "Cholesterol-related services may involve screening or monitoring, but the bill "
        "does not establish a result.",
        "Ask your provider whether results or routine follow-up need discussion.",
    ),
    "cardiology": (
        "Cardiology wording can indicate a heart-specialty service; it does not show "
        "whether additional care is needed.",
        "If your clinician recommended it, confirm whether heart-health follow-up is scheduled.",
    ),
    "nephrology": (
        "Nephrology refers to kidney-care specialty services; a bill mention is not a diagnosis.",
        "Ask the ordering care team whether any follow-up is recommended.",
    ),
    "ophthalmology": (
        "Ophthalmology wording can indicate an eye-care service; the bill cannot confirm "
        "whether more care is needed.",
        "If your care team requested it, confirm whether an eye-care follow-up is scheduled.",
    ),
    "mammogram": (
        "A mammogram is an imaging screening or diagnostic service; the bill does not "
        "include the result.",
        "Ask the ordering provider how and when to receive results or next-step instructions.",
    ),
    "MRI": (
        "MRI wording indicates an imaging service, not its result or clinical meaning.",
        "Ask the ordering clinician how to receive or discuss the imaging result.",
    ),
    "CT": (
        "CT wording indicates an imaging service, not its result or clinical meaning.",
        "Ask the ordering clinician how to receive or discuss the imaging result.",
    ),
    "emergency room": (
        "Emergency-room wording may identify a billed visit; the bill cannot confirm "
        "discharge instructions or follow-up status.",
        "If discharge instructions recommended follow-up, check next steps with the care team.",
    ),
    "refill": (
        "A refill mention relates to medication billing or dispensing and does not show "
        "whether a prescription was filled.",
        "Confirm refill timing with the prescribing clinician or pharmacy.",
    ),
    "prescription": (
        "A prescription mention does not show medication use or whether a refill is due.",
        "Ask the prescriber or pharmacist about medication questions.",
    ),
    "follow-up": (
        "Follow-up wording may be a reminder, but a bill cannot confirm whether an "
        "appointment is needed or scheduled.",
        "Confirm any recommended appointment with your care team.",
    ),
}

PROCEDURE_PATTERNS = {
    **{key: KEYWORD_PATTERNS[key] for key in ("mammogram", "MRI", "CT")},
    "ultrasound": re.compile(r"\bultrasounds?\b", re.IGNORECASE),
    "x-ray": re.compile(r"\bx[\s-]?rays?\b", re.IGNORECASE),
    "echocardiogram": re.compile(r"\bechocardiograms?\b", re.IGNORECASE),
    "colonoscopy": re.compile(r"\bcolonoscopies\b|\bcolonoscopy\b", re.IGNORECASE),
    "endoscopy": re.compile(r"\bendoscopies\b|\bendoscopy\b", re.IGNORECASE),
    "angiogram": re.compile(r"\bangiograms?\b", re.IGNORECASE),
    "biopsy": re.compile(r"\bbiopsies\b|\bbiopsy\b", re.IGNORECASE),
    "surgery": re.compile(r"\bsurger(?:y|ies)\b", re.IGNORECASE),
    "infusion": re.compile(r"\binfusions?\b", re.IGNORECASE),
    "injection": re.compile(r"\binjections?\b", re.IGNORECASE),
    "lab test": re.compile(r"\blab(?:oratory)?\s+tests?\b", re.IGNORECASE),
    "blood test": re.compile(r"\bblood\s+tests?\b", re.IGNORECASE),
    "A1C": re.compile(r"\b(?:HbA1c|A1C)(?:\s+(?:test|lab))?\b", re.IGNORECASE),
    "blood glucose test": re.compile(
        r"\bblood[\s-]+glucose(?:\s+tests?)?\b",
        re.IGNORECASE,
    ),
    "complete blood count": re.compile(r"\b(?:CBC|complete\s+blood\s+count)\b", re.IGNORECASE),
    "comprehensive metabolic panel": re.compile(
        r"\b(?:CMP|comprehensive\s+metabolic\s+panel)\b",
        re.IGNORECASE,
    ),
    "lipid panel": re.compile(r"\blipid\s+panels?\b", re.IGNORECASE),
    "urinalysis": re.compile(r"\burinalyses\b|\burinalysis\b", re.IGNORECASE),
    "ECG/EKG": re.compile(
        r"\b(?:ECG|EKG|electrocardiograms?)\b",
        re.IGNORECASE,
    ),
    "stress test": re.compile(r"\bstress\s+tests?\b", re.IGNORECASE),
    "sleep study": re.compile(r"\bsleep\s+studies?\b", re.IGNORECASE),
    "procedure": re.compile(r"\bprocedures?\b", re.IGNORECASE),
}

SCREENING_PATTERNS = {
    "mammogram": PROCEDURE_PATTERNS["mammogram"],
    "colonoscopy": PROCEDURE_PATTERNS["colonoscopy"],
    "screening": re.compile(r"\bscreening\b", re.IGNORECASE),
    "Pap test": re.compile(r"\bPap\s+(?:smear|test)\b", re.IGNORECASE),
    "cervical screening": re.compile(r"\bcervical\s+screening\b", re.IGNORECASE),
}
TEST_ACTIVITY_PATTERN = re.compile(
    r"\b(?:tests?|lab(?:oratory)?|imaging|scans?|studies)\b",
    re.IGNORECASE,
)

MONTH_NAME_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)
DATE_PATTERN = re.compile(
    rf"\b(?:"
    rf"\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|"
    rf"\d{{4}}-\d{{1,2}}-\d{{1,2}}|"
    rf"{MONTH_NAME_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}|"
    rf"\d{{1,2}}\s+{MONTH_NAME_PATTERN}\s+\d{{4}}"
    rf")\b",
    re.IGNORECASE,
)
DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%Y-%m-%d",
    "%B %d, %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%b %d %Y",
    "%d %B %Y",
    "%d %b %Y",
)

VISIT_PATTERNS = {
    "office visit": re.compile(r"\boffice\s+visits?\b", re.IGNORECASE),
    "consultation": re.compile(r"\bconsultations?\b", re.IGNORECASE),
    "appointment": re.compile(r"\bappointments?\b", re.IGNORECASE),
    "visit": re.compile(r"\bvisits?\b", re.IGNORECASE),
    "encounter": re.compile(r"\bencounters?\b", re.IGNORECASE),
    "emergency room": KEYWORD_PATTERNS["emergency room"],
}
MEDICATION_PATTERNS = {
    "prescription": KEYWORD_PATTERNS["prescription"],
    "refill": KEYWORD_PATTERNS["refill"],
    "insulin": KEYWORD_PATTERNS["insulin"],
    "medication": re.compile(r"\bmedications?\b", re.IGNORECASE),
    "pharmacy": re.compile(r"\bpharmacies\b|\bpharmacy\b", re.IGNORECASE),
}
BILLING_EVENT_PATTERNS = {
    "claim": re.compile(r"\bclaims?\b", re.IGNORECASE),
    "invoice": re.compile(r"\binvoices?\b", re.IGNORECASE),
    "statement": re.compile(r"\bstatements?\b", re.IGNORECASE),
    "payment": re.compile(r"\bpayments?\b", re.IGNORECASE),
    "charge": re.compile(r"\bcharges?\b", re.IGNORECASE),
    "balance": re.compile(r"\bbalances?\b", re.IGNORECASE),
    "due date": re.compile(r"\bdue\s+dates?\b", re.IGNORECASE),
}
CONDITION_PATTERNS = {
    "diabetes": re.compile(
        r"\b(?:type\s+[12]\s+)?diabetes(?:\s+mellitus)?\b",
        re.IGNORECASE,
    ),
    "hypertension": re.compile(r"\bhypertension\b", re.IGNORECASE),
    "high blood pressure": re.compile(r"\bhigh\s+blood\s+pressure\b", re.IGNORECASE),
    "high cholesterol": re.compile(r"\bhigh\s+cholesterol\b", re.IGNORECASE),
    "hyperlipidemia": re.compile(r"\bhyperlipid(?:emia|a)\b", re.IGNORECASE),
    "asthma": re.compile(r"\basthma\b", re.IGNORECASE),
    "COPD": re.compile(r"\bCOPD\b|\bchronic\s+obstructive\s+pulmonary\s+disease\b", re.IGNORECASE),
    "chronic kidney disease": re.compile(
        r"\b(?:CKD|chronic\s+kidney\s+disease)\b",
        re.IGNORECASE,
    ),
    "heart failure": re.compile(r"\b(?:CHF|heart\s+failure)\b", re.IGNORECASE),
    "coronary artery disease": re.compile(
        r"\b(?:CAD|coronary\s+artery\s+disease)\b",
        re.IGNORECASE,
    ),
    "atrial fibrillation": re.compile(
        r"\b(?:AFib|atrial\s+fibrillation)\b",
        re.IGNORECASE,
    ),
    "arthritis": re.compile(r"\barthritis\b", re.IGNORECASE),
    "depression": re.compile(r"\bdepression\b", re.IGNORECASE),
    "anxiety": re.compile(r"\banxiety\b", re.IGNORECASE),
}
MEDICATION_NAME_PATTERNS = {
    name: re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    for name in (
        "albuterol",
        "amlodipine",
        "amoxicillin",
        "apixaban",
        "aspirin",
        "atorvastatin",
        "empagliflozin",
        "gabapentin",
        "glipizide",
        "insulin",
        "levothyroxine",
        "lisinopril",
        "losartan",
        "metformin",
        "metoprolol",
        "omeprazole",
        "prednisone",
        "rosuvastatin",
        "semaglutide",
        "sertraline",
        "warfarin",
    )
}
PATIENT_LABEL_PATTERN = re.compile(
    r"^\s*patient(?:\s+name)?\s*(?:(?::|#|-)\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)
PROVIDER_LABEL_PATTERN = re.compile(
    r"^\s*(?:provider(?:\s+name)?|physician(?:\s+name)?|doctor(?:\s+name)?|attending\s+provider|"
    r"ordering\s+provider|rendering\s+provider|servicing\s+provider|referring\s+provider)"
    r"\s*(?:(?::|#|-)\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)
DIAGNOSIS_LABEL_PATTERN = re.compile(
    r"^\s*(?:diagnosis(?:\s+\d+)?|dx|condition|medical\s+condition|"
    r"clinical\s+impression|assessment)\s*(?:(?::|#|-)\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)
PROCEDURE_LABEL_PATTERN = re.compile(
    r"^\s*(?:procedure(?:\s+(?:name|performed))?|test(?:\s+(?:name|performed))?|"
    r"service(?:\s+description)?)\s*(?:(?::|#|-)\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)
MEDICATION_LABEL_PATTERN = re.compile(
    r"^\s*(?:medication(?:\s+name)?|drug(?:\s+name)?|prescription(?:\s+drug)?|Rx)"
    r"\s*(?:(?::|#|-)\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)
PERSON_NAME_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z'’.-]*(?:[ ,]+\s*[A-Za-z][A-Za-z'’.-]*){1,4}$"
)
PROVIDER_TITLE_PATTERN = re.compile(
    r"\b(?:Dr\.?|Doctor)\s+[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,2}",
    re.IGNORECASE,
)
PROVIDER_CREDENTIAL_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,2},?\s+"
    r"(?:M\.?D\.?|D\.?O\.?|NP|PA-C|RN|DPM)\b",
    re.IGNORECASE,
)
FIELD_HEADER_PATTERN = re.compile(
    r"^\s*(?:patient|member|subscriber|insured|provider|physician|attending|ordering|"
    r"rendering|servicing|referring|diagnosis|dx|condition|clinical impression|assessment|"
    r"procedure|test|service|medication|drug|prescription|rx|date|amount|total|charge|"
    r"balance|dos|dob|mrn)\b",
    re.IGNORECASE,
)
EVENT_ICONS = {
    "Visit": "🏥",
    "Test": "🧪",
    "Medication": "💊",
    "Screening": "🩻",
    "Billing Event": "🧾",
}

MONEY_PATTERN = re.compile(
    r"(?<!\w)\$\s*(?P<currency>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?)"
    r"|(?<![\w$./-])(?P<decimal>(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?![\w./-])"
)


def find_keywords(text: str, patterns: dict[str, re.Pattern[str]]) -> list[str]:
    """Return canonical keyword labels found anywhere in the supplied text."""
    return list(find_keyword_matches(text, patterns))


def find_keyword_matches(text: str, patterns: dict[str, re.Pattern[str]]) -> dict[str, str]:
    """Return each matched rule and the exact phrase as it appears in the bill."""
    matches = {}
    for label, pattern in patterns.items():
        match = pattern.search(text)
        if match:
            matches[label] = match.group(0)
    return matches


def make_finding(
    message: str,
    keyword_phrases: list[str],
    why_it_matters: str,
    suggested_action: str,
    confidence: str = "Medium",
) -> dict[str, str | list[str]]:
    """Attach the requested evidence and cautious context to every rule finding."""
    return {
        "message": message,
        "keyword_found": keyword_phrases,
        "why_it_matters": why_it_matters,
        "confidence": confidence,
        "suggested_action": suggested_action,
    }


def concise_finding_message(finding: dict[str, str | list[str]]) -> str:
    """Keep the first complete sentence as a quick-scan finding summary."""
    message = str(finding["message"]).strip()
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", message, maxsplit=1)
    return sentences[0] if sentences else message


def finding_action_repeats_message(
    message: str,
    action: str,
) -> bool:
    def normalize(text: str) -> str:
        return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())

    normalized_message = normalize(message)
    normalized_action = normalize(action)
    return bool(normalized_action and normalized_action in normalized_message)


def group_health_signals(
    findings: list[dict[str, str | list[str]]],
) -> list[tuple[str, list[dict[str, str | list[str]]]]]:
    """Group existing keyword matches for display without changing their rules."""
    group_names = (
        "Diabetes Monitoring Activity",
        "Cardiovascular Activity",
        "Screening Activity",
        "Imaging Activity",
        "Other Health Mentions",
    )
    grouped = {name: [] for name in group_names}
    diabetes_terms = {"diabetes", "insulin", "A1C", "blood glucose"}
    cardiovascular_terms = {"hypertension", "cholesterol", "cardiology"}
    imaging_terms = {"MRI", "CT"}

    for finding in findings:
        phrases = finding["keyword_found"]
        phrase_list = phrases if isinstance(phrases, list) else [str(phrases)]
        phrase_text = " ".join(phrase_list)
        matched_terms = set()
        for phrase in phrase_list:
            matched_terms.update(find_keyword_matches(phrase, KEYWORD_PATTERNS))
        if matched_terms.intersection(diabetes_terms):
            category = group_names[0]
        elif matched_terms.intersection(cardiovascular_terms):
            category = group_names[1]
        elif find_keyword_matches(phrase_text, SCREENING_PATTERNS):
            category = group_names[2]
        elif matched_terms.intersection(imaging_terms):
            category = group_names[3]
        else:
            category = group_names[4]
        grouped[category].append(finding)

    return [(name, grouped[name]) for name in group_names if grouped[name]]


def render_finding(
    finding: dict[str, str | list[str]],
    what_was_found: str | None = None,
) -> None:
    """Show a concise finding, context, a non-duplicated action, and its evidence."""
    message = str(finding["message"])
    short_message = concise_finding_message(finding)
    action = str(finding["suggested_action"])
    phrases = finding["keyword_found"]
    phrase_list = phrases if isinstance(phrases, list) else [str(phrases)]
    action_repeats_message = finding_action_repeats_message(message, action)

    if action_repeats_message:
        st.write("What was found / what to do:", message)
    else:
        st.write("What was found:", what_was_found or short_message)
    if not what_was_found and phrase_list and not all(
        phrase.casefold() in short_message.casefold() for phrase in phrase_list
    ):
        st.write("Evidence:", ", ".join(phrase_list))
    st.write("Why it matters:", finding["why_it_matters"])
    if not action_repeats_message:
        st.write("What to do:", action)
    st.write("Confidence:", finding["confidence"])
    if not action_repeats_message and short_message != message:
        with st.expander("Full finding context", expanded=False):
            st.write(message)


def render_accessible_notice(
    message: str,
    tone: str = "info",
    compact: bool = False,
) -> None:
    """Render a high-contrast, theme-independent status banner."""
    role = "alert" if tone == "error" else "status"
    compact_class = " accessible-alert--compact" if compact else ""
    st.markdown(
        f'<div class="accessible-alert accessible-alert--{tone}{compact_class}" role="{role}">'
        f"{html.escape(message)}</div>",
        unsafe_allow_html=True,
    )


def clean_procedure_line(line: str) -> str:
    """Normalize a line item so repeated descriptions can be compared."""
    cleaned = MONEY_PATTERN.sub(" ", line)
    cleaned = re.sub(r"\b(?:CPT|HCPCS)\s*[\w-]+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{5,6}\b", " ", cleaned)
    cleaned = re.sub(r"\b(?:qty|quantity)\s*:?\s*\d+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|")
    return cleaned


def extract_line_amounts(line: str) -> list[float]:
    """Parse currency amounts without treating bare procedure codes as prices."""
    amounts = []
    for match in MONEY_PATTERN.finditer(line):
        value = match.group("currency") or match.group("decimal")
        amounts.append(float(value.replace(",", "")))
    return amounts


def add_healthcare_entity(
    entities: dict[str, list[dict[str, object]]],
    category: str,
    value: str,
    evidence: str,
    line_index: int,
    **metadata: object,
) -> None:
    """Keep one exact text match and its source line for a healthcare entity."""
    normalized_value = re.sub(r"\s+", " ", value).strip(" \t:;|")
    if not normalized_value:
        return
    source = evidence.strip()
    if any(
        str(existing["value"]).casefold() == normalized_value.casefold()
        and existing["evidence"] == source
        for existing in entities[category]
    ):
        return
    entity: dict[str, object] = {
        "value": normalized_value,
        "evidence": source,
        "line_index": line_index,
    }
    entity.update(metadata)
    entities[category].append(entity)


def clean_labeled_value(value: str) -> str:
    """Remove trailing unrelated identifiers from a labeled name field."""
    value = re.split(
        r"(?:\s+|[,;(]\s*)(?:DOB|date\s+of\s+birth|MRN|member\s+ID|patient\s+ID)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return value.strip(" \t:;|,")


def looks_like_person_name(value: str) -> bool:
    """Validate a conservative name shape without guessing from arbitrary prose."""
    candidate = clean_labeled_value(value)
    candidate = re.sub(r"^(?:Dr\.?|Doctor)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"\s*,?\s+(?:M\.?D\.?|D\.?O\.?|NP|PA-C|RN|DPM)\s*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    return bool(PERSON_NAME_PATTERN.fullmatch(candidate))


def extract_labeled_entities(
    lines: list[str],
    entities: dict[str, list[dict[str, object]]],
    category: str,
    pattern: re.Pattern[str],
    validator=None,
) -> set[int]:
    """Extract explicitly labeled values, including a value on the next line."""
    handled_line_indexes = set()
    for line_index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue

        value = (match.group("value") or "").strip()
        evidence_lines = [line.strip()]
        value_line_index = line_index
        handled_line_indexes.add(line_index)

        if not value:
            for candidate_index in range(line_index + 1, min(len(lines), line_index + 4)):
                candidate = lines[candidate_index].strip()
                if not candidate:
                    continue
                if FIELD_HEADER_PATTERN.match(candidate):
                    break
                value = candidate
                value_line_index = candidate_index
                evidence_lines.append(candidate)
                handled_line_indexes.add(candidate_index)
                break

        value = clean_labeled_value(value)
        if not value or (validator and not validator(value)):
            continue
        add_healthcare_entity(
            entities,
            category,
            value,
            "\n".join(evidence_lines),
            value_line_index,
        )
    return handled_line_indexes


def extract_healthcare_entities(text: str) -> dict[str, list[dict[str, object]]]:
    """Extract labeled fields and common healthcare terms using local rules only."""
    lines = text.splitlines()
    categories = (
        "patients",
        "providers",
        "dates",
        "conditions",
        "procedures",
        "medications",
        "amounts",
        "screenings",
        "visits",
        "billing_events",
        "test_activity",
        "medication_mentions",
    )
    entities = {category: [] for category in categories}

    extract_labeled_entities(
        lines, entities, "patients", PATIENT_LABEL_PATTERN, looks_like_person_name
    )
    provider_label_lines = extract_labeled_entities(
        lines, entities, "providers", PROVIDER_LABEL_PATTERN, looks_like_person_name
    )
    procedure_label_lines = extract_labeled_entities(
        lines, entities, "procedures", PROCEDURE_LABEL_PATTERN
    )
    medication_label_lines = extract_labeled_entities(
        lines, entities, "medications", MEDICATION_LABEL_PATTERN
    )
    extract_labeled_entities(lines, entities, "conditions", DIAGNOSIS_LABEL_PATTERN)

    for line_index, line in enumerate(lines):
        evidence = line.strip()
        if not evidence:
            continue

        if line_index not in provider_label_lines:
            provider_matches = list(PROVIDER_TITLE_PATTERN.finditer(line))
            if not provider_matches:
                provider_matches = list(PROVIDER_CREDENTIAL_PATTERN.finditer(line))
            for match in provider_matches:
                if looks_like_person_name(match.group(0)):
                    add_healthcare_entity(
                        entities,
                        "providers",
                        match.group(0),
                        evidence,
                        line_index,
                    )

        for label, pattern in CONDITION_PATTERNS.items():
            for match in pattern.finditer(line):
                add_healthcare_entity(
                    entities,
                    "conditions",
                    match.group(0),
                    evidence,
                    line_index,
                )

        if line_index not in procedure_label_lines:
            for pattern in PROCEDURE_PATTERNS.values():
                for match in pattern.finditer(line):
                    add_healthcare_entity(
                        entities,
                        "procedures",
                        match.group(0),
                        evidence,
                        line_index,
                    )

        if line_index not in medication_label_lines:
            for pattern in MEDICATION_NAME_PATTERNS.values():
                for match in pattern.finditer(line):
                    add_healthcare_entity(
                        entities,
                        "medications",
                        match.group(0),
                        evidence,
                        line_index,
                    )

        for category, patterns in (
            ("screenings", SCREENING_PATTERNS),
            ("visits", VISIT_PATTERNS),
            ("billing_events", BILLING_EVENT_PATTERNS),
            ("test_activity", {"test activity": TEST_ACTIVITY_PATTERN}),
            ("medication_mentions", MEDICATION_PATTERNS),
        ):
            if category == "medication_mentions" and line_index in medication_label_lines:
                continue
            for pattern in patterns.values():
                for match in pattern.finditer(line):
                    add_healthcare_entity(
                        entities,
                        category,
                        match.group(0),
                        evidence,
                        line_index,
                    )

        for match in DATE_PATTERN.finditer(line):
            phrase = match.group(0)
            parsed_date = parse_date_phrase(phrase)
            if parsed_date:
                add_healthcare_entity(
                    entities,
                    "dates",
                    phrase,
                    evidence,
                    line_index,
                    parsed_date=parsed_date,
                )

        for match in MONEY_PATTERN.finditer(line):
            phrase = match.group(0)
            numeric_value = extract_line_amounts(phrase)
            add_healthcare_entity(
                entities,
                "amounts",
                phrase,
                evidence,
                line_index,
                numeric_value=numeric_value[0] if numeric_value else None,
            )

    return entities


def parse_document_dates(text: str) -> list[tuple[date, str]]:
    """Parse common numeric and written dates while retaining their exact text."""
    parsed_dates = {}
    for match in DATE_PATTERN.finditer(text):
        phrase = match.group(0)
        parsed_date = parse_date_phrase(phrase)
        if parsed_date:
            parsed_dates.setdefault(parsed_date, phrase)
    return sorted(
        ((parsed_date, phrase) for parsed_date, phrase in parsed_dates.items()),
        key=lambda item: item[0],
    )


def parse_date_phrase(phrase: str) -> date | None:
    """Convert one recognized date phrase into a date value."""
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(phrase, date_format).date()
        except ValueError:
            continue
    return None


def build_patient_journey_timeline(
    text: str,
    entities: dict[str, list[dict[str, object]]] | None = None,
) -> list[dict[str, object]]:
    """Group extracted healthcare entities into chronological, rule-labeled events."""
    entities = entities or extract_healthcare_entities(text)
    lines = text.splitlines()
    parsed_line_dates: dict[int, list[dict[str, object]]] = {}
    for entity in entities["dates"]:
        line_index = int(entity["line_index"])
        parsed_line_dates.setdefault(line_index, []).append(entity)

    grouped_dates = {}
    for line_index, line_dates in parsed_line_dates.items():
        for date_entity in line_dates:
            event_date = date_entity["parsed_date"]
            group = grouped_dates.setdefault(
                event_date,
                {
                    "date_phrases": set(),
                    "events": {},
                    "entities": {
                        category: []
                        for category in ("providers", "conditions", "procedures", "medications", "amounts")
                    },
                },
            )
            group["date_phrases"].add(date_entity["value"])

            # Include nearby service details, stopping at a different dated entry.
            context_indexes = {line_index}
            for direction in (-1, 1):
                for offset in range(1, 6):
                    context_index = line_index + direction * offset
                    if context_index < 0 or context_index >= len(lines):
                        break
                    nearby_dates = parsed_line_dates.get(context_index, [])
                    if nearby_dates and not any(
                        nearby_date["parsed_date"] == event_date for nearby_date in nearby_dates
                    ):
                        break
                    context_indexes.add(context_index)
            context_lines = [lines[index].strip() for index in sorted(context_indexes)]
            context = " ".join(line for line in context_lines if line)

            nearby_entities = {
                category: [
                    entity
                    for entity in entity_list
                    if int(entity["line_index"]) in context_indexes
                ]
                for category, entity_list in entities.items()
                if category != "dates"
            }
            for category, entity_list in group["entities"].items():
                for entity in nearby_entities[category]:
                    if not any(
                        existing["value"] == entity["value"]
                        and existing["evidence"] == entity["evidence"]
                        for existing in entity_list
                    ):
                        entity_list.append(entity)

            screening_items = nearby_entities["screenings"]
            procedure_items = nearby_entities["procedures"]
            screening_procedures = [
                entity
                for entity in procedure_items
                if find_keyword_matches(str(entity["evidence"]), SCREENING_PATTERNS)
            ]
            test_procedures = [
                entity for entity in procedure_items if entity not in screening_procedures
            ]
            event_sources = {}
            if screening_items or screening_procedures:
                event_sources["Screening"] = screening_items + screening_procedures
            if test_procedures or (nearby_entities["test_activity"] and not screening_items):
                event_sources["Test"] = test_procedures or nearby_entities["test_activity"]
            if nearby_entities["medications"] or nearby_entities["medication_mentions"]:
                event_sources["Medication"] = (
                    nearby_entities["medications"] + nearby_entities["medication_mentions"]
                )
            if nearby_entities["visits"]:
                event_sources["Visit"] = nearby_entities["visits"]
            if nearby_entities["billing_events"] or nearby_entities["amounts"]:
                event_sources["Billing Event"] = (
                    nearby_entities["billing_events"] + nearby_entities["amounts"]
                )

            for category, evidence_items in event_sources.items():
                event = group["events"].setdefault(category, [])
                for evidence_item in evidence_items:
                    if not any(
                        existing["value"] == evidence_item["value"]
                        and existing["evidence"] == evidence_item["evidence"]
                        for existing in event
                    ):
                        event.append(evidence_item)

    timeline = []
    for event_date, group in sorted(grouped_dates.items()):
        events = []
        for category in EVENT_ICONS:
            if category not in group["events"]:
                continue
            events.append(
                {
                    "category": category,
                    "icon": EVENT_ICONS[category],
                    "evidence": group["events"][category],
                }
            )
        timeline.append(
            {
                "date": event_date,
                "date_phrases": sorted(group["date_phrases"]),
                "events": events,
                "entities": group["entities"],
            }
        )
    return timeline


def render_detected_healthcare_data(
    text: str | None,
    entities: dict[str, list[dict[str, object]]],
) -> None:
    """Show every supported healthcare entity with its exact source evidence."""
    st.caption(
        "Extracted locally with deterministic text rules. A diagnosis or condition is shown "
        "only as wording found in the document; it is not a medical conclusion."
    )
    if text is None:
        render_accessible_notice("Upload a PDF with selectable text to detect healthcare data.")
        return
    if not text.strip():
        render_accessible_notice(
            "No selectable text was found in this PDF, so there is no healthcare data to display."
        )
        return

    fields = (
        ("👤 Patient", "patients"),
        ("🩺 Provider", "providers"),
        ("📅 Date", "dates"),
        ("🧾 Diagnosis / Condition Mention", "conditions"),
        ("🧪 Procedure / Test", "procedures"),
        ("💊 Medication", "medications"),
        ("💵 Amount", "amounts"),
    )
    for start in range(0, len(fields), 2):
        columns = st.columns(2, gap="large")
        for column, (title, key) in zip(columns, fields[start : start + 2]):
            with column:
                with st.container(border=True, key=f"health-data-{key}"):
                    st.markdown(f"#### {title}")
                    if entities[key]:
                        for entity in entities[key]:
                            st.text(entity["value"])
                            st.caption(entity["evidence"])
                    else:
                        st.caption("No matching text was detected.")


def render_patient_journey_timeline(
    text: str | None,
    entities: dict[str, list[dict[str, object]]],
) -> None:
    """Show dated events first and keep their supporting text collapsed."""
    st.caption(
        "Bill-listed events are grouped by date to make the document easier to scan. "
        "Use the evidence to confirm details with your care team or billing office."
    )
    timeline = build_patient_journey_timeline(text or "", entities)
    if not timeline:
        render_accessible_notice("Upload a PDF with selectable dates to build the timeline.")
        metric_columns = st.columns(3, gap="large")
        metric_columns[0].metric("Earliest Date", "—")
        metric_columns[1].metric("Latest Date", "—")
        metric_columns[2].metric("Total Events Analyzed", 0)
        return

    date_positions = [
        (entity["parsed_date"], int(entity["line_index"]))
        for entity in entities["dates"]
        if entity.get("parsed_date") and isinstance(entity.get("line_index"), int)
    ]

    def belongs_to_date(entity: dict[str, object], event_date: date) -> bool:
        line_index = entity.get("line_index")
        if not isinstance(line_index, int) or not date_positions:
            return True
        preceding_dates = [
            position for position in date_positions if position[1] <= line_index
        ]
        if preceding_dates:
            assigned_date = max(preceding_dates, key=lambda position: position[1])[0]
        else:
            assigned_date = min(date_positions, key=lambda position: position[1])[0]
        return assigned_date == event_date

    display_groups = []
    for date_group in timeline:
        display_events = []
        for event in date_group["events"]:
            evidence = [
                entity
                for entity in event["evidence"]
                if belongs_to_date(entity, date_group["date"])
            ]
            if evidence:
                display_events.append({**event, "evidence": evidence})
        display_entities = {
            category: [
                entity
                for entity in entity_list
                if belongs_to_date(entity, date_group["date"])
            ]
            for category, entity_list in date_group["entities"].items()
        }
        display_groups.append((date_group, display_events, display_entities))

    for group_index, (date_group, display_events, display_entities) in enumerate(display_groups):
        date_label = date_group["date"].strftime("%b %d, %Y")
        with st.container(border=True, key=f"timeline-date-{group_index}"):
            st.markdown(f"### 📅 {date_label}")
            if display_events:
                for event in display_events:
                    values = []
                    for evidence in event["evidence"]:
                        value = str(evidence["value"])
                        normalized_value = " ".join(re.findall(r"\w+", value.casefold()))
                        if not normalized_value:
                            continue
                        if any(
                            normalized_value == existing
                            or f" {normalized_value} " in f" {existing} "
                            for _, existing in values
                        ):
                            continue
                        values = [
                            (existing_value, existing_normalized)
                            for existing_value, existing_normalized in values
                            if f" {existing_normalized} " not in f" {normalized_value} "
                        ]
                        values.append((value, normalized_value))
                    if values:
                        event_text = html.escape(", ".join(value for value, _ in values))
                        category = html.escape(str(event["category"]))
                        st.markdown(
                            f"**{event['icon']} {category}:** {event_text}",
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("No categorized healthcare events were detected for this date.")

            evidence_items = []
            seen_evidence = set()

            def add_evidence(entity: dict[str, object]) -> None:
                evidence = str(entity["evidence"])
                if evidence and evidence not in seen_evidence:
                    seen_evidence.add(evidence)
                    evidence_items.append(evidence)

            for event in display_events:
                for entity in event["evidence"]:
                    add_evidence(entity)
            for entity_group in display_entities.values():
                for entity in entity_group:
                    add_evidence(entity)

            with st.expander(f"View Evidence — {date_label}", expanded=False):
                if date_group["date_phrases"]:
                    st.text("Date phrase(s): " + ", ".join(date_group["date_phrases"]))
                if evidence_items:
                    for evidence in evidence_items:
                        st.text(evidence)
                else:
                    st.caption("No supporting text was extracted for this date.")

    earliest = timeline[0]["date"].strftime("%b %d, %Y")
    latest = timeline[-1]["date"].strftime("%b %d, %Y")
    event_count = sum(len(events) for _, events, _ in display_groups)
    metric_columns = st.columns(3, gap="large")
    metric_columns[0].metric("Earliest Date", earliest)
    metric_columns[1].metric("Latest Date", latest)
    metric_columns[2].metric("Total Events Analyzed", event_count)


def detect_care_gaps(
    bill_text: str,
    keyword_matches: dict[str, str],
) -> list[dict[str, str | list[str]]]:
    """Find follow-up, screening, and cautious date-interval opportunities."""
    alerts = []

    # A follow-up mention is evidence of wording, not evidence that a visit was missed.
    follow_up_phrase = keyword_matches.get("follow-up")
    if follow_up_phrase:
        alerts.append(
            make_finding(
                "Possible follow-up care opportunity",
                [follow_up_phrase],
                "Follow-up wording may refer to a care plan, but the bill cannot confirm "
                "whether an appointment is due or scheduled.",
                "Ask your care team whether any follow-up mentioned in the document applies to you.",
                "Medium",
            )
        )

    # Screening terms trigger a prompt to confirm results or timing with a clinician.
    screening_matches = find_keyword_matches(bill_text, SCREENING_PATTERNS)
    if screening_matches:
        screening_phrases = list(screening_matches.values())
        alerts.append(
            make_finding(
                "Possible preventive screening opportunity",
                screening_phrases,
                "The document mentions screening-related wording or a procedure; it does not "
                "show whether screening is due or what the results were.",
                "Ask your healthcare provider about results and any screening schedule that is appropriate for you.",
                "Medium",
            )
        )

    # A 365-day gap is only a document-date heuristic; the dates may be administrative.
    document_dates = parse_document_dates(bill_text)
    monitoring_terms = {
        "diabetes",
        "insulin",
        "A1C",
        "blood glucose",
        "hypertension",
        "cholesterol",
        "cardiology",
        "nephrology",
        "ophthalmology",
    }
    monitoring_phrases = [
        phrase
        for keyword, phrase in keyword_matches.items()
        if keyword in monitoring_terms
    ]
    for (first_date, first_phrase), (second_date, second_phrase) in zip(
        document_dates,
        document_dates[1:],
    ):
        gap_days = (second_date - first_date).days
        if gap_days < CARE_GAP_THRESHOLD_DAYS:
            continue

        if monitoring_phrases:
            title = "Possible monitoring gap"
            explanation = (
                "The document contains monitoring-related wording and dates this far apart, "
                "but it does not establish that these are related service dates or that care was missed."
            )
        else:
            title = "Possible long interval between document dates"
            explanation = (
                "Long intervals can be worth clarifying, but bill dates may be administrative "
                "or unrelated and do not establish a care gap."
            )
        evidence = [first_phrase, second_phrase, *monitoring_phrases]
        alerts.append(
            make_finding(
                f"{title}: {first_phrase} and {second_phrase} are {gap_days} days apart.",
                evidence,
                explanation,
                "Confirm what each date represents and ask your provider whether any follow-up schedule applies.",
                "Low",
            )
        )
    return alerts


def analyze_bill_text(bill_text: str) -> dict[str, object]:
    """Generate educational signals and billing alerts from exact text matches."""
    keyword_matches = find_keyword_matches(bill_text, KEYWORD_PATTERNS)
    matched_keywords = list(keyword_matches)
    risks = []
    follow_up = []
    care_gap_alerts = detect_care_gaps(bill_text, keyword_matches)
    billing_issues = []
    cost_alerts = []
    recommended_actions = []
    seen_cost_alerts = set()

    # Create one educational health signal for each distinct matched term.
    health_signals = []
    for keyword, phrase in keyword_matches.items():
        why_it_matters, suggested_action = HEALTH_SIGNAL_GUIDANCE[keyword]
        health_signals.append(
            make_finding(
                f"The bill text contains the phrase {phrase!r}.",
                [phrase],
                why_it_matters,
                suggested_action,
                "Medium",
            )
        )

    # Group diabetes terms into monitoring reminders without inferring a condition.
    diabetes_terms = [term for term in ("diabetes", "insulin", "A1C", "blood glucose") if term in matched_keywords]
    if diabetes_terms:
        diabetes_phrases = [keyword_matches[term] for term in diabetes_terms]
        risks.append(
            make_finding(
                "Diabetes-related wording appears in the bill. Ask your clinician whether "
                "A1C or blood-glucose monitoring is appropriate; this keyword match is not a diagnosis.",
                diabetes_phrases,
                "These terms can relate to monitoring, but the bill does not establish a diagnosis "
                "or provide clinical results.",
                "Ask your healthcare provider whether monitoring or follow-up is appropriate.",
            )
        )
        recommended_actions.append(
            make_finding(
                "Discuss any monitoring or prescription questions with your care team.",
                diabetes_phrases,
                "The bill contains diabetes-related wording, but does not show what care is needed.",
                "Ask your healthcare provider about any monitoring or prescription questions.",
            )
        )

    # Cardiovascular-related terms trigger a cautious reminder, not a risk assessment.
    heart_terms = [
        term for term in ("cardiology", "hypertension", "cholesterol") if term in matched_keywords
    ]
    if heart_terms:
        heart_phrases = [keyword_matches[term] for term in heart_terms]
        follow_up.append(
            make_finding(
                "If your clinician recommended it, confirm that heart-health follow-up is scheduled. "
                "The bill cannot confirm whether an appointment is due or missed.",
                heart_phrases,
                "These terms may indicate heart-related services or screening; they do not establish "
                "a condition or a need for follow-up.",
                "If your clinician recommended it, confirm whether heart-health follow-up is scheduled.",
            )
        )
        recommended_actions.append(
            make_finding(
                "Ask your clinician what follow-up, if any, is appropriate for the services listed.",
                heart_phrases,
                "The bill mentions cardiovascular-related terms but cannot determine a care plan.",
                "Discuss the listed services with your healthcare provider.",
            )
        )

    # Other terms receive reminders that point back to the exact words in the bill.
    follow_up_rules = [
        (
            ("nephrology",),
            "If follow-up was recommended, confirm next steps with the ordering care team.",
            "The bill mentions a kidney-care specialty service but does not establish a diagnosis.",
        ),
        (
            ("ophthalmology",),
            "If your care team requested it, confirm whether an eye-care follow-up is scheduled.",
            "The bill mentions an eye-care service but cannot confirm follow-up status.",
        ),
        (
            ("mammogram",),
            "Ask the ordering provider how and when to receive results or any next-step instructions.",
            "The bill identifies an imaging service but does not include its result.",
        ),
        (
            ("MRI", "CT"),
            "If this imaging was ordered for you, ask the ordering clinician how to receive results.",
            "The bill identifies imaging but does not include the result or its clinical meaning.",
        ),
        (
            ("emergency room",),
            "If discharge instructions recommended follow-up, check with the care team about next steps.",
            "The bill cannot confirm discharge instructions or whether follow-up was recommended.",
        ),
        (
            ("refill", "prescription"),
            "Confirm refill timing and medication questions with the prescribing clinician or pharmacy.",
            "A medication-related billing mention does not establish how a prescription was used.",
        ),
        (
            ("follow-up",),
            "The bill mentions follow-up; confirm any recommended appointment with your care team.",
            "A bill mention does not confirm whether an appointment is due or scheduled.",
        ),
    ]
    for terms, message, why_it_matters in follow_up_rules:
        triggered = [term for term in terms if term in matched_keywords]
        if triggered:
            phrases = [keyword_matches[term] for term in triggered]
            follow_up.append(
                make_finding(
                    message,
                    phrases,
                    why_it_matters,
                    message,
                )
            )
            recommended_actions.append(
                make_finding(
                    message,
                    phrases,
                    why_it_matters,
                    message,
                )
            )

    # Exact repeated procedure descriptions are flagged for verification only.
    procedure_lines: dict[str, dict[str, object]] = {}
    source_lines = [line.strip() for line in bill_text.splitlines() if line.strip()]
    for line in source_lines:
        procedure_matches = find_keyword_matches(line, PROCEDURE_PATTERNS)
        if not procedure_matches:
            continue
        procedure_terms = list(procedure_matches)
        procedure_phrases = list(procedure_matches.values())

        description = clean_procedure_line(line)
        normalized = re.sub(r"[^a-z0-9]+", " ", description.lower()).strip()
        if not normalized:
            continue
        group = procedure_lines.setdefault(
            normalized,
            {"count": 0, "phrases": set()},
        )
        group["count"] += 1
        group["phrases"].update(procedure_phrases)

        # A charge is considered high-cost only when it is on a matching procedure line.
        for amount in extract_line_amounts(line):
            if amount >= HIGH_COST_THRESHOLD:
                cost_key = (normalized, amount)
                if cost_key in seen_cost_alerts:
                    continue
                seen_cost_alerts.add(cost_key)
                cost_alerts.append(
                    make_finding(
                        f"A line containing {', '.join(procedure_terms)} lists ${amount:,.2f}, "
                        f"at or above the ${HIGH_COST_THRESHOLD:,.2f} review threshold. "
                        "Verify the amount against the itemized bill and EOB.",
                        procedure_phrases,
                        "This matching procedure line meets the demo review threshold; that does "
                        "not establish an overcharge or billing error.",
                        "Compare the amount with the provider's itemized bill and your EOB.",
                    )
                )

    for description, group in procedure_lines.items():
        if group["count"] > 1:
            phrases = sorted(group["phrases"])
            billing_issues.append(
                make_finding(
                    f"A procedure line containing {', '.join(phrases)} appears {group['count']} "
                    "times. Verify that each entry represents a separate service.",
                    phrases,
                    "Repeated descriptions may represent separate services or a duplicate; "
                    "the text alone cannot determine which.",
                    "Ask the billing office to confirm the repeated entries.",
                )
            )
            recommended_actions.append(
                make_finding(
                    "Ask the billing office to confirm repeated procedure entries.",
                    phrases,
                    "The same procedure description appears more than once in the bill text.",
                    "Ask the billing office to confirm that each entry is correct.",
                )
            )

    # Include the terms found in the overview so even unmatched categories remain transparent.
    if matched_keywords:
        matched_phrases = list(keyword_matches.values())
        summary = (
            "Keyword mentions found in the extracted text: "
            + ", ".join(matched_phrases)
            + ". Mentions alone do not establish a diagnosis, care gap, or billing error."
        )
        summary_confidence = "High"
    else:
        summary = (
            "No configured keywords were detected in the extracted text. "
            "This rule-based check may miss other wording and does not establish that no concerns exist."
        )
        matched_phrases = []
        summary_confidence = "Low"

    for alert in cost_alerts:
        recommended_actions.append(
            make_finding(
                "Compare the flagged procedure amount with the provider's itemized bill and your EOB.",
                alert["keyword_found"],
                "A procedure line met the demo cost threshold, but that is not proof of an error.",
                "Compare the charge with your itemized bill and EOB.",
            )
        )

    return {
        "health_signals": health_signals,
        "health_summary": make_finding(
            summary,
            matched_phrases,
            "Exact keyword matches help locate relevant bill text but do not show a diagnosis or result.",
            "Review the full bill and ask your provider about any care questions.",
            summary_confidence,
        ),
        "potential_health_risks": risks,
        "possible_missed_follow_up_care": follow_up,
        "care_gap_alerts": care_gap_alerts,
        "billing_issues": billing_issues,
        "cost_alerts": cost_alerts,
        "recommended_actions": recommended_actions,
    }


def findings_for_section(
    analysis: dict[str, object],
    key: str,
) -> list[dict[str, str | list[str]]]:
    value = analysis.get(key)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [finding for finding in value if isinstance(finding, dict)]
    return []


def select_executive_findings(
    analysis: dict[str, object],
) -> list[tuple[str, dict[str, str | list[str]]]]:
    """Choose one high-value finding per category before filling remaining slots."""
    priorities = (
        ("🧭 Care Gap", "care_gap_alerts"),
        ("🧾 Billing Review", "billing_issues"),
        ("💰 High-Cost Charge", "cost_alerts"),
        ("📅 Follow-Up", "possible_missed_follow_up_care"),
        ("🩺 Health Signal", "health_signals"),
        ("⚠️ Health Risk", "potential_health_risks"),
        ("✅ Recommended Action", "recommended_actions"),
    )
    groups = [
        (label, findings)
        for label, key in priorities
        if (findings := findings_for_section(analysis, key))
    ]

    selected = [(label, findings[0]) for label, findings in groups[:3]]
    if len(selected) < 3:
        for label, findings in groups:
            selected.extend((label, finding) for finding in findings[1:])
            if len(selected) >= 3:
                break

    if not selected:
        summary = analysis.get("health_summary")
        if isinstance(summary, dict):
            selected.append(("📄 Text Review", summary))
    return selected[:3]


def render_executive_metrics(metrics: list[tuple[str, str]]) -> None:
    """Render five compact summary facts with theme-aware text and borders."""
    cards = "".join(
        (
            '<div class="executive-summary-metric" role="group" '
            f'aria-label="{html.escape(label, quote=True)}: {html.escape(value, quote=True)}">'
            f'<div class="executive-summary-label">{html.escape(label)}</div>'
            f'<div class="executive-summary-value">{html.escape(value)}</div>'
            "</div>"
        )
        for label, value in metrics
    )
    st.markdown(
        f'<div class="executive-summary-metrics" aria-label="Executive summary">{cards}</div>',
        unsafe_allow_html=True,
    )


def render_executive_findings(
    analysis: dict[str, object] | None,
    pending_upload: bool = False,
) -> None:
    st.markdown("#### Three Priority Findings")
    if analysis is None:
        if pending_upload:
            st.caption("Analyze the uploaded PDF to generate evidence-based prompts.")
        else:
            st.caption("Try the sample patient or upload a PDF to see evidence-based prompts.")
        return

    findings = select_executive_findings(analysis)
    if not findings:
        st.caption("No priority findings were generated from this document.")
        return

    columns = st.columns(3, gap="large")
    for index, (column, (label, finding)) in enumerate(zip(columns, findings)):
        with column:
            tone = {
                "💰 High-Cost Charge": "billing",
                "🩺 Health Signal": "info",
                "✅ Recommended Action": "info",
                "📄 Text Review": "info",
            }.get(label, "review")
            with st.container(
                border=True,
                key=f"analysis-finding-{tone}-executive-{index}",
            ):
                st.markdown(f"#### {label}")
                message = str(finding["message"])
                short_message = concise_finding_message(finding)
                action = str(finding["suggested_action"])
                if finding_action_repeats_message(message, action):
                    st.caption(f"What to do: {action}")
                else:
                    st.write(short_message)
                    st.caption(f"Next step: {action}")
                detail_label = {
                    "🧭 Care Gap": "View Evidence · Care Gap",
                    "🧾 Billing Review": "View Evidence · Billing Review",
                    "💰 High-Cost Charge": "View Evidence · High-Cost Charge",
                    "📅 Follow-Up": "View Evidence · Follow-Up",
                    "🩺 Health Signal": "View Evidence · Health Signal",
                    "⚠️ Health Risk": "View Evidence · Health Risk",
                    "✅ Recommended Action": "View Evidence · Recommended Action",
                    "📄 Text Review": "View Evidence · Text Review",
                }.get(label, "View Evidence")
                with st.expander(detail_label, expanded=False):
                    render_finding(finding)


def render_analysis_cards(analysis: dict[str, object]) -> None:
    """Render rule-based cards and their evidence, confidence, and actions."""
    st.subheader("🔎 Bill Review")
    st.caption(
        "Findings come from exact keyword and line-item rules over the extracted text. "
        "Confidence describes the text/rule match only, not disease likelihood or medical certainty."
    )

    informational_sections = {"health_signals", "health_summary", "recommended_actions"}
    review_sections = {
        "potential_health_risks",
        "possible_missed_follow_up_care",
        "care_gap_alerts",
        "billing_issues",
    }
    detail_labels = {
        "health_signals": "View Evidence · Health Signals",
        "health_summary": "View Evidence · Health Summary",
        "potential_health_risks": "View Evidence · Health Risks",
        "possible_missed_follow_up_care": "View Evidence · Follow-Up",
        "care_gap_alerts": "View Evidence · Care Gaps",
        "billing_issues": "View Evidence · Billing Review",
        "cost_alerts": "View Evidence · High-Cost Charges",
        "recommended_actions": "View Evidence · Recommended Actions",
    }

    # Two cards per row keep the analysis sections readable on wide screens.
    for start in range(0, len(ANALYSIS_SECTIONS), 2):
        columns = st.columns(2, gap="large")
        for column, (title, key) in zip(columns, ANALYSIS_SECTIONS[start : start + 2]):
            with column:
                if key in informational_sections:
                    tone = "info"
                elif key in review_sections:
                    tone = "review"
                else:
                    tone = "billing"
                section_id = key.replace("_", "-")
                with st.container(
                    border=True,
                    key=f"analysis-section-{tone}-{section_id}",
                ):
                    st.markdown(f"#### {title}")
                    findings = findings_for_section(analysis, key)
                    if key == "health_signals" and findings:
                        for category, grouped_findings in group_health_signals(findings):
                            signal_count = len(grouped_findings)
                            signal_label = "signal" if signal_count == 1 else "signals"
                            with st.expander(
                                f"View Evidence · {category} · {signal_count} {signal_label}",
                                expanded=False,
                            ):
                                for finding_index, finding in enumerate(grouped_findings):
                                    phrases = finding["keyword_found"]
                                    phrase_list = (
                                        phrases if isinstance(phrases, list) else [str(phrases)]
                                    )
                                    with st.container(
                                        border=True,
                                        key=(
                                            f"analysis-finding-{tone}-{section_id}-"
                                            f"{category}-{finding_index}"
                                        ),
                                    ):
                                        render_finding(
                                            finding,
                                            what_was_found=", ".join(phrase_list),
                                        )
                    else:
                        with st.expander(detail_labels[key], expanded=False):
                            if key == "cost_alerts":
                                st.caption(
                                    f"High-cost review threshold: ${HIGH_COST_THRESHOLD:,.2f}."
                                )
                            elif key == "care_gap_alerts":
                                st.caption(
                                    f"Date-gap prompt threshold: {CARE_GAP_THRESHOLD_DAYS} days."
                                )
                            if findings:
                                for finding_index, finding in enumerate(findings):
                                    with st.container(
                                        border=True,
                                        key=f"analysis-finding-{tone}-{section_id}-{finding_index}",
                                    ):
                                        render_finding(finding)
                            else:
                                st.caption(
                                    "No rule was triggered by the extracted text. "
                                    "This does not rule out a concern."
                                )

# Configure the wide dashboard layout before rendering any widgets.
st.set_page_config(
    page_title="Bill2Health | Healthcare Dashboard",
    page_icon="🩺",
    layout="wide",
)

st.markdown(
    """
    <style>
    h1, h2, h3, h4 {
        color: inherit !important;
        font-weight: 750;
        line-height: 1.25;
    }
    h1 {
        font-size: 2.5rem;
    }
    h2 {
        font-size: 2rem;
    }
    h3 {
        font-size: 1.7rem;
    }
    h4 {
        font-size: 1.25rem;
    }
    [data-testid="stHeader"] {
        background: rgba(0, 0, 0, 0);
    }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stCaptionContainer"],
    [data-testid="stText"],
    [data-testid="stWidgetLabel"] {
        color: inherit !important;
        font-size: 1.05rem;
        line-height: 1.5;
        opacity: 1 !important;
    }
    [data-testid="stCaptionContainer"] {
        font-size: 1rem;
    }
    [data-testid="stMetric"] {
        padding: 12px 8px;
    }
    [data-testid="stMetricLabel"] {
        color: inherit !important;
        font-size: 1.05rem;
        font-weight: 700;
    }
    [data-testid="stMetricValue"] {
        color: inherit !important;
        font-size: 2rem;
        font-weight: 750;
    }
    .hero {
        padding: 26px 32px;
        border-radius: 22px;
        color: white;
        background: linear-gradient(115deg, #123b5d 0%, #117b82 100%);
        margin: 4px 0 18px 0;
    }
    .hero h1 {
        color: white !important;
        margin: 0 0 6px 0;
        font-size: 2.75rem;
    }
    .hero p {
        color: #f0ffff !important;
        margin: 0;
        font-size: 1.15rem;
    }
    .eyebrow {
        color: #e7fffb;
        font-size: 1rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .section-intro {
        color: inherit !important;
        font-size: 1.1rem !important;
        margin-top: -4px;
        margin-bottom: 18px;
    }
    .stContainer {
        border-color: currentColor;
        border-radius: 14px;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 2px solid currentColor;
        border-radius: 14px;
    }
    [data-testid="stExpander"] {
        border: 1px solid currentColor;
        border-radius: 12px;
    }
    [data-testid="stExpander"] summary {
        font-size: 1.05rem;
        font-weight: 700;
    }
    div[data-testid="stButton"] > button {
        min-height: 3rem;
        padding: 0.65rem 1.2rem;
        font-size: 1.05rem;
        font-weight: 700;
        border-width: 2px;
    }
    button[data-testid="stBaseButton-primary"] {
        color: #ffffff !important;
        background-color: #174ea6 !important;
        border-color: #123b7a !important;
    }
    button[data-testid="stBaseButton-primary"]:hover {
        background-color: #123b7a !important;
        border-color: #0b2f6f !important;
    }
    button:focus-visible,
    a:focus-visible,
    [tabindex]:focus-visible {
        outline: 3px solid #ffbf47 !important;
        outline-offset: 3px;
    }
    .accessible-alert {
        border: 2px solid;
        border-radius: 12px;
        font-size: 1.05rem;
        font-weight: 650;
        line-height: 1.5;
        margin: 0.5rem 0 1rem;
        padding: 14px 18px;
    }
    .accessible-alert--compact {
        font-size: 0.98rem;
        margin: 0.35rem 0 0.7rem;
        padding: 8px 12px;
    }
    .executive-summary-metrics {
        display: grid;
        gap: 0.65rem;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        margin: 0.5rem 0 1.1rem;
    }
    .executive-summary-metric {
        background: transparent;
        border: 2px solid currentColor;
        border-radius: 12px;
        color: inherit;
        min-width: 0;
        padding: 0.65rem 0.75rem;
    }
    .executive-summary-label {
        font-size: 0.95rem;
        font-weight: 700;
        line-height: 1.3;
        overflow-wrap: normal;
        word-break: normal;
        hyphens: none;
    }
    .executive-summary-value {
        font-size: 1.35rem;
        font-weight: 750;
        line-height: 1.25;
        margin-top: 0.35rem;
        overflow-wrap: anywhere;
    }
    .accessible-alert--info,
    .accessible-alert--success {
        background-color: #e8f5e9;
        border-color: #1b5e20;
        color: #153e22;
    }
    .accessible-alert--review {
        background-color: #fff4cc;
        border-color: #8a6100;
        color: #493700;
    }
    .accessible-alert--billing,
    .accessible-alert--error {
        background-color: #fde8e7;
        border-color: #b42318;
        color: #5a1612;
    }
    .accessible-alert--timeline {
        background-color: #e6f0ff;
        border-color: #174ea6;
        color: #12335b;
    }
    [class*="st-key-analysis-section-info-"],
    [class*="st-key-analysis-finding-info-"] {
        background-color: #e8f5e9 !important;
        border: 2px solid #1b5e20 !important;
        border-radius: 12px !important;
        color: #153e22 !important;
        padding: 0.75rem !important;
    }
    [class*="st-key-analysis-section-review-"],
    [class*="st-key-analysis-finding-review-"] {
        background-color: #fff4cc !important;
        border: 2px solid #8a6100 !important;
        border-radius: 12px !important;
        color: #493700 !important;
        padding: 0.75rem !important;
    }
    [class*="st-key-analysis-section-billing-"],
    [class*="st-key-analysis-finding-billing-"] {
        background-color: #fde8e7 !important;
        border: 2px solid #b42318 !important;
        border-radius: 12px !important;
        color: #5a1612 !important;
        padding: 0.75rem !important;
    }
    [class*="st-key-analysis-section-info-"] *,
    [class*="st-key-analysis-finding-info-"] * {
        color: #153e22 !important;
    }
    [class*="st-key-analysis-section-review-"] *,
    [class*="st-key-analysis-finding-review-"] * {
        color: #493700 !important;
    }
    [class*="st-key-analysis-section-billing-"] *,
    [class*="st-key-analysis-finding-billing-"] * {
        color: #5a1612 !important;
    }
    [class*="st-key-analysis-section-info-"] [data-testid="stExpander"] summary,
    [class*="st-key-analysis-finding-info-"] [data-testid="stExpander"] summary {
        background-color: #ffffff !important;
        color: #153e22 !important;
    }
    [class*="st-key-analysis-section-review-"] [data-testid="stExpander"] summary,
    [class*="st-key-analysis-finding-review-"] [data-testid="stExpander"] summary {
        background-color: #ffffff !important;
        color: #493700 !important;
    }
    [class*="st-key-analysis-section-billing-"] [data-testid="stExpander"] summary,
    [class*="st-key-analysis-finding-billing-"] [data-testid="stExpander"] summary {
        background-color: #ffffff !important;
        color: #5a1612 !important;
    }
    [class*="st-key-analysis-section-info-"] [data-testid="stExpander"] summary *,
    [class*="st-key-analysis-finding-info-"] [data-testid="stExpander"] summary * {
        color: #153e22 !important;
    }
    [class*="st-key-analysis-section-review-"] [data-testid="stExpander"] summary *,
    [class*="st-key-analysis-finding-review-"] [data-testid="stExpander"] summary * {
        color: #493700 !important;
    }
    [class*="st-key-analysis-section-billing-"] [data-testid="stExpander"] summary *,
    [class*="st-key-analysis-finding-billing-"] [data-testid="stExpander"] summary * {
        color: #5a1612 !important;
    }
    [class*="st-key-timeline-date-"] {
        background-color: #e6f0ff !important;
        border: 2px solid #174ea6 !important;
        border-radius: 14px !important;
        color: #12335b !important;
        padding: 0.85rem !important;
    }
    [class*="st-key-timeline-date-"] * {
        color: #12335b !important;
    }
    @media (max-width: 768px) {
        .hero {
            padding: 12px 16px;
            margin-bottom: 8px;
        }
        .hero h1 {
            font-size: 1.8rem;
        }
        .hero p {
            font-size: 0.95rem;
        }
        .eyebrow {
            font-size: 0.78rem;
            margin-bottom: 2px;
        }
        h2 {
            font-size: 1.75rem;
        }
        h3 {
            font-size: 1.5rem;
        }
        .executive-summary-metrics {
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.35rem;
        }
        .executive-summary-metric {
            padding: 0.45rem;
        }
        .executive-summary-label {
            font-size: 0.82rem;
        }
        .executive-summary-value {
            font-size: 1rem;
            margin-top: 0.2rem;
        }
    }
    @media (max-width: 480px) {
        .executive-summary-metrics {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    </style>
    <div class="hero">
        <div class="eyebrow">Your care, made clearer</div>
        <h1>Bill2Health</h1>
        <p>A simpler view of your healthcare bills and next steps.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if "demo_mode" not in st.session_state:
    st.session_state["demo_mode"] = st.session_state.get("medical_bill_upload") is None
if st.session_state.get("medical_bill_upload") is not None:
    st.session_state["demo_mode"] = False

heading_column, sample_button_column = st.columns([5, 2], gap="medium")
with heading_column:
    st.subheader("Executive Summary")
with sample_button_column:
    if st.button("Try Sample Patient", type="primary"):
        st.session_state["demo_mode"] = True
        st.session_state.pop("medical_bill_upload", None)
        st.session_state["rule_bill_analysis"] = analyze_bill_text(SAMPLE_PATIENT_TEXT)
        st.session_state["rule_analysis_fingerprint"] = SAMPLE_PATIENT_FINGERPRINT

demo_mode = st.session_state.get("demo_mode", False)
uploaded_file = st.session_state.get("medical_bill_upload")
if uploaded_file is not None:
    demo_mode = False
    st.session_state["demo_mode"] = False
if demo_mode and st.session_state.get("rule_analysis_fingerprint") != SAMPLE_PATIENT_FINGERPRINT:
    st.session_state["rule_bill_analysis"] = analyze_bill_text(SAMPLE_PATIENT_TEXT)
    st.session_state["rule_analysis_fingerprint"] = SAMPLE_PATIENT_FINGERPRINT

bill_text = None
bill_fingerprint = None
pdf_status = None
pdf_error = None
pdf_error_detail = None
pdf_page_count = 0

# Read the active document before the executive summary so its first screen is current.
if demo_mode:
    bill_text = SAMPLE_PATIENT_TEXT
    bill_fingerprint = SAMPLE_PATIENT_FINGERPRINT
elif uploaded_file is not None:
    try:
        pdf_bytes = uploaded_file.getvalue()
        if not pdf_bytes:
            pdf_error = "The selected PDF is empty."
        else:
            bill_fingerprint = hashlib.sha256(pdf_bytes).hexdigest()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_document:
                if pdf_document.needs_pass:
                    pdf_error = (
                        "This PDF is password-protected. Upload an unlocked PDF to extract its text."
                    )
                else:
                    bill_text = "\n\n".join(page.get_text("text") for page in pdf_document)
                    pdf_page_count = len(pdf_document)
                    pdf_status = f"Extracted text from {uploaded_file.name} ({pdf_page_count} pages)."
    except (fitz.FileDataError, RuntimeError) as error:
        pdf_error = (
            "We couldn't read this PDF. Check that the file is a valid, uncorrupted PDF and try again."
        )
        pdf_error_detail = str(error)

# Discard analysis results as soon as the active document changes or is removed.
if st.session_state.get("rule_analysis_fingerprint") != bill_fingerprint:
    st.session_state.pop("rule_bill_analysis", None)
    st.session_state.pop("rule_analysis_fingerprint", None)

analysis_result = st.session_state.get("rule_bill_analysis")
if not isinstance(analysis_result, dict) or st.session_state.get(
    "rule_analysis_fingerprint"
) != bill_fingerprint:
    analysis_result = None

healthcare_entities = extract_healthcare_entities(bill_text or "")

if demo_mode:
    render_accessible_notice(
        "This is a fictional demonstration patient for hackathon evaluation.",
        compact=True,
    )
elif pdf_error:
    render_accessible_notice(pdf_error, "error")
elif uploaded_file is not None:
    render_accessible_notice(
        "Your uploaded PDF is reviewed locally with rule-based prompts, not AI."
    )
else:
    render_accessible_notice("Try the sample patient or upload a PDF to begin.")

if (
    uploaded_file is not None
    and bill_text
    and bill_fingerprint
    and analysis_result is None
    and st.button("Analyze Extracted Bill", type="secondary")
):
    analysis_result = analyze_bill_text(bill_text)
    st.session_state["rule_bill_analysis"] = analysis_result
    st.session_state["rule_analysis_fingerprint"] = bill_fingerprint

patient_entities = healthcare_entities["patients"]
patient_name = str(patient_entities[0]["value"]) if patient_entities else "Not identified"
documents_analyzed = int(analysis_result is not None and bill_fingerprint is not None)
health_signal_count = len(findings_for_section(analysis_result or {}, "health_signals"))
billing_prompt_count = len(findings_for_section(analysis_result or {}, "billing_issues"))
billing_prompt_count += len(findings_for_section(analysis_result or {}, "cost_alerts"))
recommended_action_count = len(findings_for_section(analysis_result or {}, "recommended_actions"))

render_executive_metrics(
    [
        ("Patient", patient_name),
        ("Documents analyzed", str(documents_analyzed)),
        ("Health Signals Found", str(health_signal_count)),
        ("Billing Review Prompts", str(billing_prompt_count)),
        ("Recommended Actions", str(recommended_action_count)),
    ]
)
render_executive_findings(
    analysis_result,
    pending_upload=uploaded_file is not None and bill_text is not None,
)

with st.expander("🧭 Patient Journey Timeline", expanded=False):
    render_patient_journey_timeline(bill_text, healthcare_entities)

with st.expander("📄 Upload or replace a PDF bill", expanded=False):
    st.caption(
        "Text is extracted locally. Scanned-image OCR is not included; review prompts use "
        "document text and line items."
    )
    st.file_uploader(
        "Choose a medical bill (PDF)",
        type=["pdf"],
        key="medical_bill_upload",
    )

if pdf_error:
    render_accessible_notice(pdf_error, "error")
    if pdf_error_detail:
        st.caption(f"PDF reader detail: {pdf_error_detail}")
elif uploaded_file is not None:
    if pdf_status:
        render_accessible_notice(pdf_status, "success")
    if bill_text is not None:
        with st.expander("View Extracted Bill"):
            if bill_text.strip():
                st.text(bill_text)
            else:
                render_accessible_notice(
                    "No selectable text was found. Scanned-image OCR is not available in this demo."
                )
elif demo_mode and bill_text is not None:
    with st.expander("View Sample Patient Bill"):
        st.text(bill_text)

if analysis_result is not None:
    render_analysis_cards(analysis_result)
else:
    with st.expander("General guidance", expanded=False):
        st.subheader("💡 Health Insights")
        st.markdown(
            '<p class="section-intro">Helpful context, without making assumptions about your health.</p>',
            unsafe_allow_html=True,
        )
        insight_cols = st.columns(3, gap="medium")
        with insight_cols[0]:
            with st.container(border=True):
                st.markdown("#### 🩺 Clinical context")
                st.write("A medical bill does not contain enough information to assess your health.")
        with insight_cols[1]:
            with st.container(border=True):
                st.markdown("#### 🗂️ Records")
                st.write("No health records are connected. Keep care questions for your clinician.")
        with insight_cols[2]:
            with st.container(border=True):
                st.markdown("#### 🌿 A good next step")
                st.write("For symptoms or treatment concerns, contact a qualified healthcare professional.")

        st.subheader("🔎 Billing Issues to Check")
        st.markdown(
            '<p class="section-intro">Common review prompts—not issues detected in your bill.</p>',
            unsafe_allow_html=True,
        )
        issue_cols = st.columns(3, gap="medium")
        with issue_cols[0]:
            with st.container(border=True):
                st.markdown("#### 🔁 Duplicate line items")
                st.write("Compare repeated services and dates against your visit records.")
        with issue_cols[1]:
            with st.container(border=True):
                st.markdown("#### 🧾 Unclear charges")
                st.write("Ask for an itemized statement if a description or amount is unfamiliar.")
        with issue_cols[2]:
            with st.container(border=True):
                st.markdown("#### 🛡️ Insurance adjustments")
                st.write("Compare the bill with your insurer's Explanation of Benefits (EOB).")

        st.subheader("✅ Recommended Actions")
        action_cols = st.columns(3, gap="medium")
        actions = [
            ("1", "Request an itemized bill", "Ask the provider to explain any charge you don't recognize."),
            ("2", "Match it to your EOB", "Check dates, allowed amounts, and patient responsibility."),
            ("3", "Call the billing office", "Ask about corrections, financial assistance, or a payment plan."),
        ]
        for column, (number, title, description) in zip(action_cols, actions):
            with column:
                with st.container(border=True):
                    st.markdown(f"#### {number}. {title}")
                    st.write(description)

with st.expander("View Evidence · Detected Healthcare Data", expanded=False):
    render_detected_healthcare_data(bill_text, healthcare_entities)

# Keep the medical and financial disclaimer visible throughout the demo.
st.caption(
    "Bill2Health is a demo, not medical or financial advice. "
    "Confirm health questions with a clinician and billing questions with your provider or insurer."
)
