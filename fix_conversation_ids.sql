UPDATE messages m
SET conversation_id = (
    SELECT c.id
    FROM conversations c
    WHERE (c.user1_id = m.sender_id AND c.user2_id = m.receiver_id)
       OR (c.user1_id = m.receiver_id AND c.user2_id = m.sender_id)
    LIMIT 1
)
WHERE conversation_id IS NULL;