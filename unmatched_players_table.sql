CREATE TABLE unmatched_players (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    team_id UUID REFERENCES teams(id) ON DELETE CASCADE,
    match_id UUID REFERENCES matches(id) ON DELETE SET NULL,
    match_day TEXT,
    position TEXT DEFAULT 'Unknown',
    status TEXT DEFAULT 'Unmatched',
    detection_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add RLS policy to allow authenticated users to access the unmatched players data
ALTER TABLE unmatched_players ENABLE ROW LEVEL SECURITY;

CREATE POLICY unmatched_players_policy ON unmatched_players
  FOR ALL USING (auth.role() IN ('authenticated', 'service_role'));

-- Add view for easier querying with team names
CREATE OR REPLACE VIEW unmatched_players_view AS
SELECT 
    up.id,
    up.name,
    up.team_id,
    t.name AS team_name,
    up.match_id,
    up.match_day,
    up.position,
    up.status,
    up.detection_date,
    up.notes,
    up.created_at,
    up.updated_at
FROM unmatched_players up
JOIN teams t ON up.team_id = t.id;

-- Add indexes for better query performance
CREATE INDEX idx_unmatched_players_team_id ON unmatched_players(team_id);
CREATE INDEX idx_unmatched_players_match_id ON unmatched_players(match_id);
CREATE INDEX idx_unmatched_players_name ON unmatched_players(name); 