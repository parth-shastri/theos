ALTER TABLE research_items RENAME TO research_scratchpad;
DROP INDEX research_item_run;
CREATE INDEX research_scratchpad_run ON research_scratchpad(run, created);
