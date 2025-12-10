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

CREATE TABLE IF NOT EXISTS season_stat_category (
    category_code VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    description VARCHAR(255)
);

-- ✅ REQUIRED SEED DATA (matches stored procedure EXACTLY)
INSERT IGNORE INTO season_stat_category (category_code, display_name, description) VALUES
('PLINKS', 'Plinks', 'Total plinks recorded'),
('HITS', 'Hits', 'Successful hits'),
('MISSES', 'Misses', 'Missed attempts'),
('PLUNKS', 'Plunks', 'Plunks ending a round'),
('KICKS', 'Kicks', 'Kick penalties'),
('SELF_FG', 'Self Field Goals', 'Accidental self-scoring'),
('DROPS', 'Drops', 'Opponent cup drops'),
('CATCHES', 'Catches', 'Opponent catches'),
('PLAYER_WINS', 'Player Wins', 'Matches won'),
('PLAYER_LOSSES', 'Player Losses', 'Matches lost');
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

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_TallyAndFinalizeGame$$

CREATE PROCEDURE sp_TallyAndFinalizeGame (
    IN p_game_id INT
)
BEGIN
    -- == 1. DECLARE VARIABLES ==
    DECLARE v_league_id INT;
    DECLARE v_season_year INT;
    DECLARE v_home_team INT;
    DECLARE v_away_team INT;
    DECLARE v_home_wins INT;
    DECLARE v_away_wins INT;
    DECLARE v_winner_team_id INT;
    DECLARE v_loser_team_id INT;
    DECLARE v_game_status VARCHAR(50);

    -- == 2. VALIDATE GAME ==
    SELECT 
        g.league_id, l.season_year, g.home_team, g.away_team, g.status
    INTO 
        v_league_id, v_season_year, v_home_team, v_away_team, v_game_status
    FROM 
        game g
    JOIN 
        league l ON g.league_id = l.league_id
    WHERE 
        g.game_id = p_game_id;

    IF v_game_status = 'Finalized' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Game is already finalized.';
    END IF;

    -- == 3. DETERMINE WINNER ==
    SELECT COUNT(*) INTO v_home_wins
    FROM game_round
    WHERE game_id = p_game_id AND winner_team_id = v_home_team;

    SELECT COUNT(*) INTO v_away_wins
    FROM game_round
    WHERE game_id = p_game_id AND winner_team_id = v_away_team;
    
    IF v_home_wins > v_away_wins THEN
        SET v_winner_team_id = v_home_team;
        SET v_loser_team_id = v_away_team;
    ELSE
        SET v_winner_team_id = v_away_team;
        SET v_loser_team_id = v_home_team;
    END IF;

    -- == 4A. TALLY ATTACKER STATS ==
    INSERT INTO player_season_metric (league_id, season_year, player_id, category_code, metric_value)
    SELECT
        v_league_id,
        v_season_year,
        player_id,
        CASE
            WHEN event_type LIKE 'PLINK%' THEN 'PLINKS'
            WHEN event_type LIKE 'HIT%' THEN 'HITS'
            WHEN event_type = 'MISS' THEN 'MISSES'
            WHEN event_type = 'PLUNK' THEN 'PLUNKS'
            WHEN event_type = 'KICK' THEN 'KICKS'
            WHEN event_type = 'SELF_FIELD_GOAL' THEN 'SELF_FG'
            ELSE NULL
        END AS stat_category,
        COUNT(*) AS event_count
    FROM round_event
    WHERE game_id = p_game_id
    GROUP BY player_id, stat_category
    HAVING stat_category IS NOT NULL
    ON DUPLICATE KEY UPDATE
        metric_value = metric_value + VALUES(metric_value);

    -- == 4B. TALLY DEFENDER STATS ==
    INSERT INTO player_season_metric (league_id, season_year, player_id, category_code, metric_value)
    SELECT
        v_league_id,
        v_season_year,
        opponent_player_id AS player_id,
        CASE
            WHEN event_type LIKE '%_DROP' THEN 'DROPS'
            WHEN event_type LIKE '%_CATCH' THEN 'CATCHES'
            ELSE NULL
        END AS stat_category,
        COUNT(*) AS event_count
    FROM round_event
    WHERE 
        game_id = p_game_id 
        AND opponent_player_id IS NOT NULL 
    GROUP BY player_id, stat_category
    HAVING stat_category IS NOT NULL
    ON DUPLICATE KEY UPDATE
        metric_value = metric_value + VALUES(metric_value);

    -- == 5. TALLY WINS & LOSSES ==
    INSERT INTO player_season_metric (league_id, season_year, player_id, category_code, metric_value)
    SELECT v_league_id, v_season_year, player_id, 'PLAYER_WINS', 1
    FROM team_membership
    WHERE team_id = v_winner_team_id
    ON DUPLICATE KEY UPDATE metric_value = metric_value + 1;

    INSERT INTO player_season_metric (league_id, season_year, player_id, category_code, metric_value)
    SELECT v_league_id, v_season_year, player_id, 'PLAYER_LOSSES', 1
    FROM team_membership
    WHERE team_id = v_loser_team_id
    ON DUPLICATE KEY UPDATE metric_value = metric_value + 1;

    -- == 6. FINALIZE GAME ==
    UPDATE game SET status = 'Finalized' WHERE game_id = p_game_id;
    
    SELECT 'Game finalized and stats tallied successfully.' AS result;

END$$

-- Reset delimiter back to standard semicolon
DELIMITER ;