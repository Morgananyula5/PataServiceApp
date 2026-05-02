-- bookings table
CREATE TABLE IF NOT EXISTS bookings (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(255) NOT NULL,
    customer_email VARCHAR(255) NOT NULL,
    location VARCHAR(255) NOT NULL,
    service_date TIMESTAMP DEFAULT NULL,
    rescheduled_date TIMESTAMP DEFAULT NULL,
    status VARCHAR(50) DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bookings_provider_id ON bookings(provider_id);
CREATE INDEX IF NOT EXISTS idx_bookings_customer_email ON bookings(customer_email);

-- users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    last_login TIMESTAMP,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    county VARCHAR(255),
    sub_county VARCHAR(255)
);

-- providers table
CREATE TABLE IF NOT EXISTS providers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    profile_picture VARCHAR(255),
    phone VARCHAR(255) NOT NULL,
    service_description TEXT NOT NULL,
    areas_served TEXT NOT NULL,
    sub_county VARCHAR(255) NOT NULL DEFAULT '',
    local_area VARCHAR(255) DEFAULT '',
    availability VARCHAR(255) NOT NULL,
    custom_availability TEXT DEFAULT NULL,
    pricing TEXT NOT NULL,
    service_category TEXT,
    activity_status TEXT DEFAULT 'Active',
    last_viewed_ratings_count INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_providers_user_id ON providers(user_id);

-- conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user1_id INTEGER NOT NULL,
    user2_id INTEGER NOT NULL,
    FOREIGN KEY (user1_id) REFERENCES users(id),
    FOREIGN KEY (user2_id) REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_conversation_idx ON conversations (LEAST(user1_id, user2_id), GREATEST(user1_id, user2_id));

-- messages table
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    media_type VARCHAR(50) DEFAULT NULL,
    media_path VARCHAR(255) DEFAULT NULL,
    reaction VARCHAR(50) DEFAULT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE,
    is_pinned BOOLEAN DEFAULT FALSE,
    is_starred BOOLEAN DEFAULT FALSE,
    conversation_id INTEGER NOT NULL,
    deleted_for TEXT DEFAULT '',
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (receiver_id) REFERENCES users(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_timestamp ON messages(conversation_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_sender_receiver ON messages (conversation_id, sender_id, receiver_id, is_read);


-- Add index for unread message count optimization
CREATE INDEX IF NOT EXISTS idx_messages_receiver_read_conversation 
ON messages(receiver_id, is_read, conversation_id);


-- Add unique index for case-insensitive email uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS unique_email_lower_idx ON users (LOWER(email));

-- Ensure indexes exist for the new endpoint
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_timestamp ON messages (conversation_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_receiver_id_is_read ON messages (receiver_id, is_read);
-- These are already present, but confirm they’re optimized

-- portfolios table
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL UNIQUE, -- Added UNIQUE constraint
    skills TEXT NOT NULL,
    certifications TEXT,
    experience TEXT NOT NULL,
    work_samples TEXT,
    github_links TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_portfolios_provider_id ON portfolios(provider_id);

-- ratings table
CREATE TABLE IF NOT EXISTS ratings (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER,
    provider_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    overall_rating INTEGER NOT NULL,
    quality INTEGER,
    punctuality INTEGER,
    communication INTEGER,
    feedback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES bookings (id) ON DELETE SET NULL,
    FOREIGN KEY (provider_id) REFERENCES providers (id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ratings_provider_id ON ratings(provider_id);

-- payment_details table
CREATE TABLE IF NOT EXISTS payment_details (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    method VARCHAR(50) NOT NULL,
    mpesa_suboption VARCHAR(50),
    mpesa_name VARCHAR(255),
    phone_number VARCHAR(255),
    business_name VARCHAR(255),
    till_number VARCHAR(255),
    business_number VARCHAR(255),
    account_number VARCHAR(255),
    account_name VARCHAR(255),
    FOREIGN KEY (provider_id) REFERENCES providers (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_payment_details_provider_id ON payment_details(provider_id);

-- verification_codes table
CREATE TABLE IF NOT EXISTS verification_codes (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_codes_email ON verification_codes(email);
CREATE INDEX IF NOT EXISTS idx_verification_codes_expires_at ON verification_codes(expires_at);

-- notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);


DROP TABLE IF EXISTS feedback;


-- feedback table
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    feedback TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_viewed BOOLEAN DEFAULT FALSE,
    user_type VARCHAR(50) DEFAULT 'customer',
    FOREIGN KEY (customer_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_feedback_customer_id ON feedback(customer_id);
CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp);


-- Existing tables and indexes remain unchanged; only adding new indexes

-- Index for latest message subquery
CREATE INDEX IF NOT EXISTS idx_messages_conversation_timestamp_deleted 
ON messages (conversation_id, timestamp DESC) 
WHERE deleted_for IS NULL OR deleted_for NOT LIKE '%<user_id>%';

-- Index for unread count subquery
CREATE INDEX IF NOT EXISTS idx_messages_receiver_conversation_unread 
ON messages (receiver_id, conversation_id, is_read) 
WHERE is_read = FALSE AND (deleted_for IS NULL OR deleted_for NOT LIKE '%<user_id>%');

-- Ensure conversations table is indexed for user lookups
CREATE INDEX IF NOT EXISTS idx_conversations_users 
ON conversations (user1_id, user2_id);


-- Additional indexes for inbox query optimization
CREATE INDEX IF NOT EXISTS idx_conversations_user_ids ON conversations (user1_id, user2_id);
CREATE INDEX IF NOT EXISTS idx_messages_receiver_unread ON messages (receiver_id, is_read, conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages (timestamp DESC);


-- Additional indexes for optimized inbox query
CREATE INDEX IF NOT EXISTS idx_conversations_user1_id ON conversations (user1_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user2_id ON conversations (user2_id);


-- service_media table for provider posts
CREATE TABLE IF NOT EXISTS service_media (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    media_path VARCHAR(255) NOT NULL,
    media_type VARCHAR(50) NOT NULL,  -- 'image' or 'video'
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_service_media_provider_id ON service_media(provider_id);
CREATE INDEX IF NOT EXISTS idx_service_media_timestamp ON service_media(timestamp DESC);
-- Index for service_media timestamp queries
CREATE INDEX IF NOT EXISTS idx_service_media_provider_timestamp ON service_media (provider_id, timestamp DESC);


-- Alter users table to add phone column if not exists
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(255);

-- Add unique index on phone
CREATE UNIQUE INDEX IF NOT EXISTS unique_phone_idx ON users (phone);

-- Make email nullable (if it was NOT NULL)
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;

-- stories table (updated with media_type enforcement and viewed index)
DROP TABLE IF EXISTS stories;
CREATE TABLE stories (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL,
    media_path VARCHAR(255) NOT NULL,
    media_type VARCHAR(50) NOT NULL DEFAULT 'image',  -- Enforce NOT NULL with default (fixes undefined/null crashes)
    text TEXT DEFAULT '',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    viewed BOOLEAN DEFAULT FALSE,  -- Explicit DEFAULT FALSE for unviewed stories
    FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_stories_provider_id ON stories(provider_id);
CREATE INDEX IF NOT EXISTS idx_stories_expires_at ON stories(expires_at);
CREATE INDEX IF NOT EXISTS idx_stories_viewed ON stories(viewed);  -- For filtering unviewed
CREATE INDEX IF NOT EXISTS idx_stories_provider_viewed ON stories(provider_id, viewed);  -- For fast unviewed count/deletion
CREATE INDEX IF NOT EXISTS idx_stories_provider_id_deleted ON stories(provider_id, id) WHERE expires_at > CURRENT_TIMESTAMP;  -- For fast lookup by provider_id and id

-- Ensure stories table has id for deletion
ALTER TABLE stories ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;
-- Add index for fast lookup by provider_id and id
CREATE INDEX IF NOT EXISTS idx_stories_provider_id_deleted ON stories(provider_id, id) WHERE expires_at > CURRENT_TIMESTAMP;

-- New table for per-customer story views
DROP TABLE IF EXISTS stories_views;
CREATE TABLE stories_views (
    id SERIAL PRIMARY KEY,
    story_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(story_id, customer_id)
);
CREATE INDEX IF NOT EXISTS idx_stories_views_customer ON stories_views(customer_id);
CREATE INDEX IF NOT EXISTS idx_stories_views_story ON stories_views(story_id);

-- Update existing stories to set media_type if null
UPDATE stories SET media_type = 'image' WHERE media_type IS NULL;
ALTER TABLE stories ALTER COLUMN media_type SET NOT NULL;
ALTER TABLE stories ALTER COLUMN media_type SET DEFAULT 'image';


-- Ensure county and sub_county columns exist (for existing databases)
ALTER TABLE users ADD COLUMN IF NOT EXISTS county VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS sub_county VARCHAR(255);

-- Ensure phone column exists and is nullable (for phone/email flexibility)
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(255);

-- Add unique index on phone if not exists (allows NULLs)
CREATE UNIQUE INDEX IF NOT EXISTS unique_phone_idx ON users (phone) WHERE phone IS NOT NULL;

-- rating_replies table
CREATE TABLE IF NOT EXISTS rating_replies (
    id SERIAL PRIMARY KEY,
    rating_id INTEGER NOT NULL,
    reply TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rating_id) REFERENCES ratings (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rating_replies_rating_id ON rating_replies(rating_id);

ALTER TABLE stories 
ALTER COLUMN viewed SET DEFAULT FALSE;

-- Ensure all existing non-expired stories are marked unviewed (in case of old data)
UPDATE stories 
SET viewed = FALSE 
WHERE viewed IS NULL 
  AND expires_at > NOW();

-- Add key_skills column to providers table
ALTER TABLE providers 
ADD COLUMN IF NOT EXISTS key_skills TEXT DEFAULT '';

CREATE TABLE provider_phone_otps (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(20),
    otp VARCHAR(10),
    expires_at TIMESTAMP,
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- customer_posts table
CREATE TABLE IF NOT EXISTS customer_posts (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    content TEXT DEFAULT '',
    media_path VARCHAR(255) DEFAULT NULL,
    media_type VARCHAR(50) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_customer_posts_customer_id ON customer_posts(customer_id);
CREATE INDEX IF NOT EXISTS idx_customer_posts_created_at ON customer_posts(created_at DESC);