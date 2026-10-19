-- Schema for the image retrieval service (simplified from the design guide, section 6).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS entities (
  entity_id      uuid PRIMARY KEY,
  slug           text NOT NULL DEFAULT '',
  canonical_name text NOT NULL,
  name_fold      text NOT NULL,
  entity_type    text NOT NULL DEFAULT 'person',   -- person | organization | place
  category_raw   text,
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Several people can share a name, so alias_fold is not unique.
CREATE TABLE IF NOT EXISTS entity_aliases (
  entity_id  uuid NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  alias      text NOT NULL,
  alias_fold text NOT NULL,
  PRIMARY KEY (entity_id, alias_fold)
);
CREATE INDEX IF NOT EXISTS alias_fold_idx ON entity_aliases(alias_fold);
CREATE INDEX IF NOT EXISTS alias_trgm_idx ON entity_aliases USING gin(alias_fold gin_trgm_ops);

-- One row per CSV observation of an (entity, image locator) pair, approved or not.
CREATE TABLE IF NOT EXISTS links (
  source_file     text NOT NULL,
  row_no          integer NOT NULL,
  entity_id       uuid NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  image_url       text,
  local_path      text,
  source_url      text,
  description     text,
  approval_status text NOT NULL CHECK (approval_status IN ('approved','rejected','unknown')),
  reject_reason   text,
  PRIMARY KEY (source_file, row_no)
);
CREATE INDEX IF NOT EXISTS links_url_idx ON links(image_url);

-- Download state per locator, so the downloader can resume and report its funnel.
CREATE TABLE IF NOT EXISTS fetches (
  locator    text PRIMARY KEY,
  status     text NOT NULL CHECK (status IN ('ok','failed')),
  image_id   uuid,
  error      text,
  attempts   integer NOT NULL DEFAULT 1,
  fetched_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS images (
  image_id       uuid PRIMARY KEY,
  content_sha256 text NOT NULL UNIQUE,
  thumb_path     text NOT NULL,
  width          integer NOT NULL,
  height         integer NOT NULL,
  byte_size      bigint NOT NULL,
  image_url      text,
  source_url     text,
  description    text,
  search_text    text NOT NULL DEFAULT '',
  search_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, search_text)) STORED,
  embedding      vector,
  is_serving     boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS images_tsv_idx ON images USING gin(search_tsv);

-- Effective label per (image, entity) after merging observations.
CREATE TABLE IF NOT EXISTS image_entities (
  image_id        uuid NOT NULL REFERENCES images(image_id) ON DELETE CASCADE,
  entity_id       uuid NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  approval_status text NOT NULL CHECK (approval_status IN ('approved','rejected','unknown')),
  PRIMARY KEY (image_id, entity_id)
);
CREATE INDEX IF NOT EXISTS image_entities_entity_idx
  ON image_entities(entity_id, image_id) WHERE approval_status = 'approved';

CREATE TABLE IF NOT EXISTS relations (
  relation_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  subject_id   uuid NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  predicate    text NOT NULL CHECK (predicate IN
                 ('parent_of','spouse_of','founded','member_of','located_in')),
  object_id    uuid NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  source_url   text NOT NULL,
  evidence     text NOT NULL DEFAULT '',
  verified     boolean NOT NULL DEFAULT false,
  CHECK (subject_id <> object_id),
  UNIQUE (subject_id, predicate, object_id)
);
CREATE INDEX IF NOT EXISTS relations_fwd_idx ON relations(subject_id, predicate) WHERE verified;
CREATE INDEX IF NOT EXISTS relations_rev_idx ON relations(object_id, predicate) WHERE verified;

-- Extra attributes used by relation phrases ("con trai" needs gender of the child).
ALTER TABLE entities ADD COLUMN IF NOT EXISTS gender text CHECK (gender IN ('male','female'));

CREATE TABLE IF NOT EXISTS meta (
  key   text PRIMARY KEY,
  value text NOT NULL
);
