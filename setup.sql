-- Supabase SQL setup for Telegram personal calendar tracker bot
-- Run this in the Supabase SQL Editor to initialize the database schema.

-- Users: Telegram profiles, gamification stats, streak tracking.
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    streak INTEGER DEFAULT 0,
    last_entry_date DATE
);

-- Day entries: daily records per user with tags and optional note.
CREATE TABLE IF NOT EXISTS day_entries (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    tags TEXT[] DEFAULT '{}',
    note TEXT DEFAULT '',
    created_at TIMAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, date)
);

-- Goals: day/week/month goals with completion and optional closing note.
CREATE TABLE IF NOT EXISTS goals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('day', 'week', 'month')),
    period_start DATE NOT NULL,
    title TEXT NOT NULL,
    completed BOOLEAN DEFAULT FALSE,
    closing_note TEXT DEFAULT '',
    closed_at TIMESTAMPTZ,
    created_at TIMAMPTZ DEFAULT NOW()
);

-- Disable Row Level Security for server-side bot access.
ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE day_entries DISABLE ROW LEVEL SECURITY;
ALTER TABLE goals DISABLE ROW LEVEL SECURITY;