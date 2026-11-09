-- ============================================================================
-- Cassava Disease Detection & Hotspot Mapping System
-- PostgreSQL + PostGIS schema (aligned with the project ERD)
-- Apply with:  psql -U cassava -d cassava -f backend/app/db/schema.sql
-- ============================================================================

-- Note (Debian/Ubuntu): the package registers the control file via
-- update-alternatives as postgis.control; if you see "extension postgis is
-- not available", the alternatives link is missing (see docs/DATABASE.md).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Enumerations
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('farmer', 'officer', 'admin');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE disease_label AS ENUM ('CMD', 'CBSD', 'Healthy', 'Uncertain');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE severity_level AS ENUM ('Low', 'Moderate', 'High');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE risk_level AS ENUM ('Low', 'Emerging', 'High');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- USERS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name     VARCHAR(120) NOT NULL,
    phone         VARCHAR(20)  UNIQUE,
    email         VARCHAR(160) UNIQUE,
    role          user_role    NOT NULL DEFAULT 'farmer',
    password_hash VARCHAR(255) NOT NULL,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT users_has_contact CHECK (phone IS NOT NULL OR email IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- FARMS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS farms (
    farm_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    farm_name  VARCHAR(120) NOT NULL,
    district   VARCHAR(80),
    latitude   DOUBLE PRECISION CHECK (latitude  BETWEEN -90  AND 90),
    longitude  DOUBLE PRECISION CHECK (longitude BETWEEN -180 AND 180),
    location   GEOGRAPHY(Point, 4326),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_farms_location ON farms USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_farms_user     ON farms (user_id);

-- ---------------------------------------------------------------------------
-- MODEL VERSIONS (registry of deployed MobileNetV2 artefacts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_versions (
    model_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_tag      VARCHAR(50)  NOT NULL UNIQUE,
    architecture     VARCHAR(50)  NOT NULL DEFAULT 'MobileNetV2',
    file_path        VARCHAR(255),
    val_accuracy     DOUBLE PRECISION,
    is_active        BOOLEAN      NOT NULL DEFAULT FALSE,
    deployed_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- LEAF IMAGES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leaf_images (
    image_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    farm_id         UUID REFERENCES farms(farm_id) ON DELETE SET NULL,
    file_path       VARCHAR(255) NOT NULL,
    latitude        DOUBLE PRECISION CHECK (latitude  BETWEEN -90  AND 90),
    longitude       DOUBLE PRECISION CHECK (longitude BETWEEN -180 AND 180),
    gps_location    GEOGRAPHY(Point, 4326),
    gps_accuracy_m  REAL,
    captured_at     TIMESTAMPTZ,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_leaf_images_location ON leaf_images USING GIST (gps_location);
CREATE INDEX IF NOT EXISTS idx_leaf_images_user     ON leaf_images (user_id);

-- ---------------------------------------------------------------------------
-- DIAGNOSES (one per image; produced by the CNN)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id         UUID NOT NULL UNIQUE REFERENCES leaf_images(image_id) ON DELETE CASCADE,
    model_version_id UUID REFERENCES model_versions(model_version_id) ON DELETE SET NULL,
    disease_label    disease_label NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL
                     CHECK (confidence_score >= 0 AND confidence_score <= 1),
    inferred_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_diagnoses_label ON diagnoses (disease_label);
CREATE INDEX IF NOT EXISTS idx_diagnoses_time  ON diagnoses (inferred_at DESC);

-- ---------------------------------------------------------------------------
-- ADVICE (1-to-1 with diagnosis, produced by the Risk Logic Engine)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS advice (
    advice_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    diagnosis_id   UUID NOT NULL UNIQUE REFERENCES diagnoses(diagnosis_id) ON DELETE CASCADE,
    advice_text    TEXT NOT NULL,
    severity_level severity_level NOT NULL,
    generated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RISK RULES (admin-configurable templates used by the Risk Engine)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_rules (
    rule_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    disease_label   disease_label NOT NULL,
    min_confidence  DOUBLE PRECISION NOT NULL DEFAULT 0.60,
    severity_level  severity_level NOT NULL,
    advice_template TEXT NOT NULL,
    updated_by      UUID REFERENCES users(user_id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- HOTSPOT CLUSTERS (derived by DBSCAN from confident CMD/CBSD diagnoses)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hotspot_clusters (
    cluster_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    centroid          GEOGRAPHY(Point, 4326) NOT NULL,
    latitude          DOUBLE PRECISION NOT NULL,
    longitude         DOUBLE PRECISION NOT NULL,
    radius_m          DOUBLE PRECISION NOT NULL,
    member_count      INTEGER NOT NULL,
    dominant_disease  disease_label NOT NULL,
    risk_level        risk_level NOT NULL,
    algorithm         VARCHAR(20) NOT NULL DEFAULT 'DBSCAN',
    eps_m             DOUBLE PRECISION NOT NULL,
    min_samples       INTEGER NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clusters_centroid ON hotspot_clusters USING GIST (centroid);

-- Junction: which diagnoses belong to which cluster
CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id   UUID NOT NULL REFERENCES hotspot_clusters(cluster_id) ON DELETE CASCADE,
    diagnosis_id UUID NOT NULL REFERENCES diagnoses(diagnosis_id) ON DELETE CASCADE,
    PRIMARY KEY (cluster_id, diagnosis_id)
);

-- ---------------------------------------------------------------------------
-- GEOGRAPHY SYNC TRIGGERS
-- Every writer (ORM, seed script, raw psql) stores plain lat/lon floats;
-- these triggers keep the PostGIS GEOGRAPHY column in sync so spatial
-- indexes and ST_* queries always see the point.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sync_farms_location() RETURNS trigger AS $$
BEGIN
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.location := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
    ELSE
        NEW.location := NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_farms_sync_location ON farms;
CREATE TRIGGER trg_farms_sync_location
    BEFORE INSERT OR UPDATE OF latitude, longitude ON farms
    FOR EACH ROW EXECUTE FUNCTION sync_farms_location();

CREATE OR REPLACE FUNCTION sync_leaf_image_location() RETURNS trigger AS $$
BEGIN
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.gps_location := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
    ELSE
        NEW.gps_location := NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_leaf_images_sync_location ON leaf_images;
CREATE TRIGGER trg_leaf_images_sync_location
    BEFORE INSERT OR UPDATE OF latitude, longitude ON leaf_images
    FOR EACH ROW EXECUTE FUNCTION sync_leaf_image_location();

CREATE OR REPLACE FUNCTION sync_cluster_centroid() RETURNS trigger AS $$
BEGIN
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.centroid := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_clusters_sync_centroid ON hotspot_clusters;
CREATE TRIGGER trg_clusters_sync_centroid
    BEFORE INSERT OR UPDATE OF latitude, longitude ON hotspot_clusters
    FOR EACH ROW EXECUTE FUNCTION sync_cluster_centroid();

-- ---------------------------------------------------------------------------
-- DIAGNOSIS FEEDBACK (officer verification of a diagnosis)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS diagnosis_feedback (
    feedback_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    diagnosis_id   UUID NOT NULL REFERENCES diagnoses(diagnosis_id) ON DELETE CASCADE,
    officer_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    verified_label disease_label NOT NULL,
    comments       TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
