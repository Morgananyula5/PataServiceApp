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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    availability VARCHAR(255) NOT NULL,
    custom_availability TEXT DEFAULT NULL,
    pricing TEXT NOT NULL,
    service_category TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

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
    conversation_id INTEGER,
    deleted_for TEXT DEFAULT '',
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (receiver_id) REFERENCES users(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

-- portfolios table
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL,
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