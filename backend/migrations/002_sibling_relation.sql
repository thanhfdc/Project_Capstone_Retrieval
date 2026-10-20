-- Siblings: "em gái của X", "anh trai của X". Re-runnable like every migration here.
ALTER TABLE relations DROP CONSTRAINT IF EXISTS relations_predicate_check;
ALTER TABLE relations ADD CONSTRAINT relations_predicate_check CHECK (predicate IN
  ('parent_of','spouse_of','sibling_of','founded','member_of','located_in'));
