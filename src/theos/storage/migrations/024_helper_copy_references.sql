-- Helper copies (context objects of kind 'delegate_checkpoint') are now kept by count,
-- not by checkpoint reference. Older checkpoints still list them.
--
-- A checkpoint_references record stores only id, owner, and session for each listed
-- object. After retention deletes a helper copy row, nothing shows that a missing id
-- was a helper copy, and retention would defer the whole chat. Remove helper copy ids
-- from these records now, while the context_objects rows still show their kind.
--
-- SQLite does not promise that a subquery result keeps its JSON subtype. json() marks
-- the array as JSON again, so json_set never stores it as one quoted string.
UPDATE records
SET value = json_set(
    value,
    '$.objects',
    json((
        SELECT json_group_array(json(item.value))
        FROM json_each(records.value, '$.objects') AS item
        WHERE NOT EXISTS (
            SELECT 1 FROM context_objects helper
            WHERE helper.id = json_extract(item.value, '$.id')
            AND helper.kind = 'delegate_checkpoint'
        )
    ))
)
WHERE kind = 'checkpoint_references'
AND EXISTS (
    SELECT 1
    FROM json_each(records.value, '$.objects') AS item
    JOIN context_objects helper ON helper.id = json_extract(item.value, '$.id')
    WHERE helper.kind = 'delegate_checkpoint'
);
