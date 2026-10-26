-- Incremental load of the Kimball warehouse from operational tables.
-- Idempotent: re-running for the same window upserts the same rows.
-- Window: last 35 days (covers late-arriving / revised data).

-- Dimensions -------------------------------------------------------------------
INSERT INTO warehouse.dim_disease (disease_code, disease_name, category, icd10_code, transmission_mode,
                                   vaccine_preventable, nationally_notifiable, severity_weight)
SELECT code, name, category, icd10,
       CASE category WHEN 'respiratory' THEN 'respiratory' WHEN 'vector-borne' THEN 'vector'
                     WHEN 'enteric' THEN 'foodborne' ELSE 'contact' END,
       code IN ('MEASLES', 'INFLUENZA', 'CLI'), nationally_notifiable, severity_weight
FROM diseases
ON CONFLICT (disease_code) DO UPDATE
SET disease_name = EXCLUDED.disease_name, category = EXCLUDED.category, severity_weight = EXCLUDED.severity_weight;

-- SCD type 2 on location: close current rows whose attributes changed, then insert new versions.
UPDATE warehouse.dim_location l
SET effective_to = current_date - 1, is_current = false
FROM regions r
WHERE l.fips_code = r.id AND l.is_current
  AND (l.county_name, l.state_code, l.latitude, l.longitude) IS DISTINCT FROM (r.name, r.state, r.lat, r.lon);

INSERT INTO warehouse.dim_location (fips_code, county_name, state_code, latitude, longitude, geom, effective_from)
SELECT r.id, r.name, r.state, r.lat, r.lon, r.geom, current_date
FROM regions r
WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_location l WHERE l.fips_code = r.id AND l.is_current);

INSERT INTO warehouse.dim_population (location_key, year, age_group, sex, population_count)
SELECT l.location_key, extract(year FROM current_date)::smallint, 'ALL', 'ALL', r.population
FROM regions r JOIN warehouse.dim_location l ON l.fips_code = r.id AND l.is_current
ON CONFLICT (location_key, year, age_group, sex) DO UPDATE SET population_count = EXCLUDED.population_count;

-- Facts ------------------------------------------------------------------------
INSERT INTO warehouse.fact_cases (event_date, date_key, location_key, disease_key, population_key, case_count,
                                  confirmed_count, ed_visit_count, hospitalized_count, death_count, source_batch_id)
SELECT s.observed_on, to_char(s.observed_on, 'YYYYMMDD')::int, l.location_key, d.disease_key, p.population_key,
       coalesce(s.cases, 0)::int, coalesce(s.cases, 0)::int, coalesce(s.ed_visits, 0)::int,
       coalesce(s.admissions, 0)::int, coalesce(s.deaths, 0)::int, s.batch_id
FROM daily_signals s
JOIN warehouse.dim_location l ON l.fips_code = s.region_id AND l.is_current
JOIN warehouse.dim_disease d  ON d.disease_code = s.disease_code
LEFT JOIN warehouse.dim_population p ON p.location_key = l.location_key AND p.age_group = 'ALL' AND p.sex = 'ALL'
     AND p.year = extract(year FROM s.observed_on)
WHERE s.observed_on >= current_date - 35
ON CONFLICT (event_date, location_key, disease_key, date_key) DO UPDATE
SET case_count = EXCLUDED.case_count, confirmed_count = EXCLUDED.confirmed_count,
    ed_visit_count = EXCLUDED.ed_visit_count, hospitalized_count = EXCLUDED.hospitalized_count,
    death_count = EXCLUDED.death_count, source_batch_id = EXCLUDED.source_batch_id, loaded_at = now();

INSERT INTO warehouse.fact_lab_results (event_date, date_key, location_key, disease_key, test_type,
                                        tests_performed, positive_tests, sequenced_count)
SELECT lr.specimen_date, to_char(lr.specimen_date, 'YYYYMMDD')::int, l.location_key, d.disease_key,
       coalesce(lr.test_type, 'all'), count(*), count(*) FILTER (WHERE lr.result = 'positive'),
       count(*) FILTER (WHERE lr.lineage IS NOT NULL)
FROM lab_reports lr
JOIN warehouse.dim_location l ON l.fips_code = lr.region_id AND l.is_current
JOIN warehouse.dim_disease d  ON d.disease_code = lr.disease_code
WHERE lr.specimen_date >= current_date - 35
GROUP BY 1, 2, 3, 4, 5
ON CONFLICT (event_date, location_key, disease_key, test_type, date_key) DO UPDATE
SET tests_performed = EXCLUDED.tests_performed, positive_tests = EXCLUDED.positive_tests,
    sequenced_count = EXCLUDED.sequenced_count, loaded_at = now();

INSERT INTO warehouse.dim_facility (facility_id, facility_name, facility_type, location_key)
SELECT DISTINCT ON (h.facility_id) h.facility_id, h.facility_id, 'hospital', l.location_key
FROM hospital_admissions h JOIN warehouse.dim_location l ON l.fips_code = h.region_id AND l.is_current
WHERE NOT EXISTS (SELECT 1 FROM warehouse.dim_facility f WHERE f.facility_id = h.facility_id AND f.is_current);

INSERT INTO warehouse.fact_hospitalizations (event_date, date_key, location_key, facility_key, disease_key,
                                             new_admissions, icu_admissions, ventilated_count)
SELECT h.admit_date, to_char(h.admit_date, 'YYYYMMDD')::int, l.location_key, f.facility_key, d.disease_key,
       count(*), count(*) FILTER (WHERE h.icu), count(*) FILTER (WHERE h.ventilated)
FROM hospital_admissions h
JOIN warehouse.dim_location l ON l.fips_code = h.region_id AND l.is_current
JOIN warehouse.dim_facility f ON f.facility_id = h.facility_id AND f.is_current
JOIN warehouse.dim_disease d  ON d.disease_code = h.disease_code
WHERE h.admit_date >= current_date - 35
GROUP BY 1, 2, 3, 4, 5
ON CONFLICT (event_date, facility_key, disease_key) DO UPDATE
SET new_admissions = EXCLUDED.new_admissions, icu_admissions = EXCLUDED.icu_admissions,
    ventilated_count = EXCLUDED.ventilated_count, loaded_at = now();

INSERT INTO warehouse.fact_alerts (alert_id, event_date, date_key, location_key, disease_key, risk_level,
                                   risk_level_rank, risk_score, outbreak_probability, anomaly_score, status,
                                   minutes_to_acknowledge)
SELECT a.id, a.created_at::date, to_char(a.created_at, 'YYYYMMDD')::int, l.location_key, d.disease_key,
       a.risk_level, array_position(ARRAY['green','yellow','orange','red'], a.risk_level::text) - 1,
       e.risk_score, e.outbreak_probability, e.anomaly_score, a.status,
       (extract(epoch FROM a.acknowledged_at - a.created_at) / 60)::int
FROM alerts a
JOIN warehouse.dim_location l ON l.fips_code = a.region_id AND l.is_current
JOIN warehouse.dim_disease d  ON d.disease_code = a.disease_code
LEFT JOIN outbreak_events e ON e.id = a.outbreak_event_id
WHERE a.created_at >= current_date - 35
ON CONFLICT (alert_id, event_date) DO UPDATE
SET status = EXCLUDED.status, minutes_to_acknowledge = EXCLUDED.minutes_to_acknowledge, loaded_at = now();

-- Weekly rollup: TimescaleDB refreshes its continuous aggregate by policy; on RDS refresh the plain view here.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    IF (SELECT ispopulated FROM pg_matviews WHERE matviewname = 'daily_signals_weekly') THEN
      REFRESH MATERIALIZED VIEW CONCURRENTLY daily_signals_weekly;
    ELSE
      REFRESH MATERIALIZED VIEW daily_signals_weekly;
    END IF;
  END IF;
END $$;
