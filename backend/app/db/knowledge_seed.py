"""Starter knowledge base for the copilot.

These are concise, original operational summaries written for SentinelHealth.
Agencies should load their own authoritative documents (CDC case definitions,
state communicable-disease manuals, HAN bulletins) via ``POST /copilot/documents``
or the ``knowledge_ingest`` Airflow DAG.
"""

DOCUMENTS = [
    {
        "title": "Signal triage protocol for statistical aberrations",
        "doc_type": "protocol",
        "source": "SentinelHealth operational playbook v1",
        "disease_code": None,
        "content": """A statistical signal is not an outbreak. When the platform raises a YELLOW or higher alert, the on-call epidemiologist should complete triage within one business day (ORANGE: same day; RED: within 4 hours).

Triage steps: (1) Check data quality first: late-arriving batches, duplicate submissions, changes in the number of reporting facilities, and new test sites can all create artificial increases. Use the lineage view to see which batch produced the values. (2) Confirm the signal across independent sources: an increase seen in emergency-department syndromic data, laboratory positivity and wastewater together is far more credible than one seen in a single feed. (3) Review the line list for epidemiological linkage: common exposures, settings (schools, long-term care, restaurants), clustering in time and place. (4) Decide: close as artefact, monitor, or open an investigation.

Document the decision on the alert (acknowledge or resolve with a note). Adjudicated alerts are used to monitor model precision and retrain thresholds.""",
    },
    {
        "title": "Measles: surveillance and response essentials",
        "doc_type": "case_definition",
        "source": "SentinelHealth summary; consult CDC/CSTE case definition for official criteria",
        "disease_code": "MEASLES",
        "content": """Clinical picture: generalized maculopapular rash lasting three days or more, fever of 38.3°C (101°F) or higher, and cough, coryza or conjunctivitis. Measles is highly contagious; a single confirmed case is a public-health emergency requiring immediate notification.

Laboratory confirmation: IgM serology or RT-PCR from throat/nasopharyngeal swab or urine; genotyping supports source attribution.

Response actions: isolate the case through four days after rash onset; identify contacts exposed during the infectious period (four days before through four days after rash onset); offer post-exposure MMR within 72 hours or immune globulin within 6 days to eligible susceptible contacts; exclude susceptible contacts from high-risk settings; issue provider and public communication for exposure sites.

Because baseline incidence is near zero, any cluster of two or more epidemiologically linked cases should be treated as an outbreak; the platform therefore applies a severity weighting to measles risk scores.""",
    },
    {
        "title": "Influenza and respiratory virus season monitoring",
        "doc_type": "guideline",
        "source": "SentinelHealth summary",
        "disease_code": "INFLUENZA",
        "content": """Seasonal influenza activity is tracked with influenza-like illness (ILI) visits from syndromic surveillance, laboratory percent positivity, hospital admissions and wastewater viral concentration. Season onset is usually declared when percent positivity and ILI exceed the jurisdictional baseline for two consecutive weeks.

Unusual signals to escalate even in season: activity far above the seasonal forecast interval, early-season surges, severe illness in children or healthy adults, novel or untypeable influenza A results (possible novel subtype — notify immediately), and clusters in long-term care facilities.

Recommended actions when activity is elevated: promote vaccination and antiviral treatment for high-risk patients, alert hospitals to surge planning when forecast admissions are high or very high, and coordinate infection-control guidance for congregate settings.""",
    },
    {
        "title": "Dengue: vector-borne disease alert guidance",
        "doc_type": "guideline",
        "source": "SentinelHealth summary",
        "disease_code": "DENGUE",
        "content": """Dengue transmission requires Aedes mosquitoes and is concentrated in warm, humid areas (e.g., Puerto Rico, Florida, the Gulf Coast and the U.S.–Mexico border region) with peaks after the rainy season. Most U.S. mainland cases are travel-associated; locally acquired cases signal active transmission and warrant rapid vector-control response.

Warning signs of severe dengue include abdominal pain, persistent vomiting, mucosal bleeding, lethargy and rising hematocrit with falling platelets; clinicians should be reminded of warning signs when the platform forecasts rising hospitalization risk.

Response: confirm with NS1 antigen or RT-PCR in the first week and IgM afterwards; investigate travel history; coordinate with vector-control districts for source reduction and adult mosquito control around case residences; issue public messaging on bite prevention and standing water.""",
    },
    {
        "title": "Foodborne illness cluster investigation",
        "doc_type": "protocol",
        "source": "SentinelHealth summary",
        "disease_code": "FOODBORNE",
        "content": """Foodborne clusters typically present as a sudden, geographically focused increase in gastrointestinal syndromic visits, followed by laboratory-confirmed enteric pathogens (Salmonella, STEC, Norovirus, Listeria). Whole-genome sequencing links cases across jurisdictions.

When the spatial hotspot detector identifies a cluster with high relative risk, interview cases using a standardized hypothesis-generating questionnaire, compare exposures to background rates, and coordinate with environmental health to inspect implicated establishments. Notify regulatory partners when a commercially distributed product is suspected.

Short incubation (hours) and vomiting predominance suggest toxin or norovirus; longer incubation with bloody diarrhea suggests STEC, which requires urgent clinician advisories regarding hemolytic uremic syndrome.""",
    },
    {
        "title": "Risk levels and notification policy",
        "doc_type": "protocol",
        "source": "SentinelHealth operational playbook v1",
        "disease_code": None,
        "content": """GREEN: activity within the expected seasonal range; routine monitoring. YELLOW: a statistical signal or elevated outbreak likelihood (30–60%); jurisdiction epidemiologists are notified in-app and by email for triage. ORANGE: high outbreak likelihood (60% or more), rapid growth, or high forecast hospital burden; the state health department is additionally notified by email and SMS. RED: high likelihood combined with high-consequence disease, very high forecast hospital burden or rapid multi-signal growth; CDC analysts and healthcare networks are notified (webhook/HAN-style feed).

Alerts are de-duplicated for seven days per disease and region unless the level escalates. Every alert includes the reasons and top model drivers so that reviewers can understand why it was raised. Final determination of an outbreak and of public communication remains with the responsible health officer.""",
    },
    {
        "title": "COVID-like illness and wastewater surveillance interpretation",
        "doc_type": "guideline",
        "source": "SentinelHealth summary",
        "disease_code": "CLI",
        "content": """Wastewater viral concentration typically leads reported cases by four to seven days because shedding begins before symptoms and before testing. Rising wastewater trends with stable case counts can indicate under-testing rather than absence of transmission.

Interpretation: evaluate the trend over at least two weeks of samples, account for flow normalization and sampling changes, and compare with syndromic COVID-like illness emergency-department visits. A sustained increase across multiple sewersheds suggests community-wide transmission; a single-site spike may reflect a facility or an event.

Actions: communicate trend levels to hospitals for staffing, emphasize vaccination and testing access, and prioritise protection of long-term care facilities when wastewater and admissions rise together.""",
    },
]
