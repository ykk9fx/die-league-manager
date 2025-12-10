-- DDL for League Manager API Schema (MySQL) - Standardized to snake_case

-- 1. User Account Table
CREATE TABLE user_account (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash CHAR(60) NOT NULL
);

-- 2. League Table
CREATE TABLE league (
    league_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    season_year YEAR NOT NULL,
    status VARCHAR(50) NOT NULL,
    UNIQUE KEY (name, season_year)
);

-- 3. Role Assignment Table (Junction Table)
CREATE TABLE role_assignment (
    user_id INT NOT NULL,
    league_id INT NOT NULL,
    role VARCHAR(50) NOT NULL,
    PRIMARY KEY (user_id, league_id),
    FOREIGN KEY (user_id) REFERENCES user_account(user_id) ON DELETE CASCADE,
    FOREIGN KEY (league_id) REFERENCES league(league_id) ON DELETE CASCADE
);

-- 4. Player Table
CREATE TABLE player (
    player_id INT AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL
);

-- 5. Team Table
CREATE TABLE team (
    team_id INT AUTO_INCREMENT PRIMARY KEY,
    league_id INT NOT NULL,
    team_name VARCHAR(255) NOT NULL,
    FOREIGN KEY (league_id) REFERENCES league(league_id) ON DELETE CASCADE,
    UNIQUE KEY (league_id, team_name)
);

-- 6. Team Membership Table
CREATE TABLE team_membership (
    team_id INT NOT NULL,
    player_id INT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    joined_at DATETIME NOT NULL,
    left_at DATETIME,
    PRIMARY KEY (team_id, player_id),
    FOREIGN KEY (team_id) REFERENCES team(team_id) ON DELETE CASCADE,
    FOREIGN KEY (player_id) REFERENCES player(player_id) ON DELETE CASCADE,
    CHECK (left_at IS NULL OR joined_at <= left_at)
);

-- 7. Game Table
CREATE TABLE game (
    game_id INT AUTO_INCREMENT PRIMARY KEY,
    league_id INT NOT NULL,
    status VARCHAR(50) NOT NULL,
    scheduled_at DATETIME NOT NULL,
    home_team INT NOT NULL,
    away_team INT NOT NULL,
    playoff_flag BOOLEAN DEFAULT FALSE,
    round_best_of INT,
    FOREIGN KEY (league_id) REFERENCES league(league_id) ON DELETE CASCADE,
    FOREIGN KEY (home_team) REFERENCES team(team_id),
    FOREIGN KEY (away_team) REFERENCES team(team_id),
    CHECK (home_team <> away_team)
);

-- 8. Game Round Table
CREATE TABLE game_round (
    game_id INT NOT NULL,
    round_number INT NOT NULL,
    status VARCHAR(50) NOT NULL,
    winner_team_id INT,
    PRIMARY KEY (game_id, round_number),
    FOREIGN KEY (game_id) REFERENCES game(game_id) ON DELETE CASCADE,
    FOREIGN KEY (winner_team_id) REFERENCES team(team_id)
);

-- 9. Round Score Table
CREATE TABLE round_score (
    game_id INT NOT NULL,
    round_number INT NOT NULL,
    team_id INT NOT NULL,
    little_points INT DEFAULT 0,
    big_point_awarded BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (game_id, round_number, team_id),
    FOREIGN KEY (game_id, round_number) REFERENCES game_round(game_id, round_number) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES team(team_id)
);

-- 10. Round Event Table
CREATE TABLE round_event (
    event_id INT AUTO_INCREMENT PRIMARY KEY,
    game_id INT NOT NULL,
    round_number INT NOT NULL,
    sequence_number INT NOT NULL,
    player_team_id INT NOT NULL,
    player_id INT NOT NULL,
    opponent_team_id INT,
    opponent_player_id INT,
    event_type VARCHAR(50) NOT NULL,
    player_lp_delta INT DEFAULT 0,
    opponent_lp_delta INT DEFAULT 0,
    notes TEXT,
    UNIQUE KEY (game_id, round_number, sequence_number),
    FOREIGN KEY (game_id, round_number) REFERENCES game_round(game_id, round_number) ON DELETE CASCADE,
    FOREIGN KEY (player_team_id) REFERENCES team(team_id),
    FOREIGN KEY (player_id) REFERENCES player(player_id),
    FOREIGN KEY (opponent_team_id) REFERENCES team(team_id),
    FOREIGN KEY (opponent_player_id) REFERENCES player(player_id)
);

-- 11. Season Stat Category Table
CREATE TABLE season_stat_category (
    category_code VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL
);

-- 12. Player Season Metric Table
CREATE TABLE player_season_metric (
    league_id INT NOT NULL,
    season_year YEAR NOT NULL,
    player_id INT NOT NULL,
    category_code VARCHAR(50) NOT NULL,
    metric_value DECIMAL(10, 2) NOT NULL,
    PRIMARY KEY (league_id, season_year, player_id, category_code),
    FOREIGN KEY (league_id) REFERENCES league(league_id) ON DELETE CASCADE,
    FOREIGN KEY (player_id) REFERENCES player(player_id) ON DELETE CASCADE,
    FOREIGN KEY (category_code) REFERENCES season_stat_category(category_code) ON DELETE CASCADE
);

-- 13. Season Award Table
CREATE TABLE season_award (
    league_id INT NOT NULL,
    season_year YEAR NOT NULL,
    category_code VARCHAR(50) NOT NULL,
    winner_player_id INT NOT NULL,
    metric_value DECIMAL(10, 2) NOT NULL,
    PRIMARY KEY (league_id, season_year, category_code),
    FOREIGN KEY (league_id) REFERENCES league(league_id) ON DELETE CASCADE,
    FOREIGN KEY (category_code) REFERENCES season_stat_category(category_code) ON DELETE CASCADE,
    FOREIGN KEY (winner_player_id) REFERENCES player(player_id) ON DELETE CASCADE
);