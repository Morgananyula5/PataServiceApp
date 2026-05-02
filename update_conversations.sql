DO $$
DECLARE
    msg RECORD;
    conv_id INTEGER;
BEGIN
    FOR msg IN SELECT id, sender_id, receiver_id, conversation_id FROM messages WHERE conversation_id IS NULL LOOP
        -- Check if a conversation exists
        SELECT id INTO conv_id
        FROM conversations
        WHERE (user1_id = msg.sender_id AND user2_id = msg.receiver_id)
           OR (user1_id = msg.receiver_id AND user2_id = msg.sender_id)
        LIMIT 1;

        -- Create a new conversation if it doesn't exist
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
