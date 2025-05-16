# Player Appearances Database Schema

## Tables Structure

```
teams
┌─────────────┐
│ id (PK)     │
│ name        │
│ created_at  │
└─────────────┘
       ▲
       │
       │
players
┌─────────────────┐
│ id (PK)         │
│ name            │
│ team_id (FK)    │◄─┐
│ position        │  │
│ status          │  │
│ value           │  │
│ salary          │  │
│ total_appearances│  │
│ created_at      │  │
└─────────────────┘  │
       ▲             │
       │             │
       │             │
appearances          │
┌─────────────────┐  │
│ id (PK)         │  │
│ player_id (FK)  │  │
│ match_day       │  │
│ date            │  │
│ appeared        │  │
│ match_id (FK)   │──┤
│ created_at      │  │
└─────────────────┘  │
       ▲             │
       │             │
       │             │
matches             │
┌─────────────────┐  │
│ id (PK)         │  │
│ home_team_id (FK)├─┘
│ away_team_id (FK)├─┘
│ match_day       │
│ date            │
│ created_at      │
└─────────────────┘
```

## Tables Details

### teams
- **id**: UUID, Primary Key
- **name**: TEXT, Unique, Team name
- **created_at**: TIMESTAMP, Auto-generated creation timestamp

### players
- **id**: UUID, Primary Key
- **name**: TEXT, Player name
- **team_id**: UUID, Foreign Key to teams(id)
- **position**: TEXT, Player's position (FWD, MID, DEF, GK)
- **status**: TEXT, Player status (Active, Inactive, etc.)
- **value**: NUMERIC, Player market value
- **salary**: NUMERIC, Player salary
- **total_appearances**: INTEGER, Total number of appearances
- **created_at**: TIMESTAMP, Auto-generated creation timestamp

### matches
- **id**: UUID, Primary Key
- **home_team_id**: UUID, Foreign Key to teams(id)
- **away_team_id**: UUID, Foreign Key to teams(id)
- **match_day**: TEXT, Match day identifier (e.g. MD1, MD2)
- **date**: DATE, Match date
- **created_at**: TIMESTAMP, Auto-generated creation timestamp

### appearances
- **id**: UUID, Primary Key
- **player_id**: UUID, Foreign Key to players(id)
- **match_day**: TEXT, Match day identifier
- **date**: DATE, Appearance date
- **appeared**: BOOLEAN, Whether player appeared in match
- **match_id**: UUID, Foreign Key to matches(id)
- **created_at**: TIMESTAMP, Auto-generated creation timestamp

## Relationships

1. **teams** ▶ **players**: One-to-many (A team has many players)
2. **teams** ▶ **matches** (as home_team): One-to-many (A team has many home matches)
3. **teams** ▶ **matches** (as away_team): One-to-many (A team has many away matches)
4. **players** ▶ **appearances**: One-to-many (A player has many appearances)
5. **matches** ▶ **appearances**: One-to-many (A match has many player appearances) 