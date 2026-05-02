-- Step 1: Assign conversation_id to messages missing it
DO $$
DECLARE
    msg RECORD;
    conv_id INTEGER;
BEGIN
    FOR msg IN SELECT id, sender_id, receiver_id FROM messages WHERE conversation_id IS NULL LOOP
        -- Check for existing conversation
        SELECT id INTO conv_id
        FROM conversations
        WHERE (user1_id = msg.sender_id AND user2_id = msg.receiver_id)
           OR (user1_id = msg.receiver_id AND user2_id = msg.sender_id)
        LIMIT 1;

        -- If no conversation exists, create one
        IF conv_id IS NULL THEN
            INSERT INTO conversations (user1_id, user2_id)
            VALUES (LEAST(msg.sender_id, msg.receiver_id), GREATEST(msg.sender_id, msg.receiver_id))
            RETURNING id INTO conv_id;
        END IF;

        -- Update the message with the conversation_id
        UPDATE messages
        SET conversation_id = conv_id
        WHERE id = msg.id;
    END LOOP;
END $$;

-- Step 2: Ensure all conversations have at least one message linked (optional cleanup)
DELETE FROM conversations
WHERE id NOT IN (SELECT DISTINCT conversation_id FROM messages WHERE conversation_id IS NOT NULL);