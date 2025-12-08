-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Oct 28, 2025 at 01:49 AM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.0.30

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `die_league_db`
--

DELIMITER $$
--
-- Procedures
--
CREATE DEFINER=`root`@`localhost` PROCEDURE `sp_TallyAndFinalizeGame` (IN `p_game_id` INT)   BEGIN
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
        Game g
    JOIN 
        League l ON g.league_id = l.league_id
    WHERE 
        g.game_id = p_game_id FOR UPDATE;

    IF v_game_status = 'Completed' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Game is already completed.';
    END IF;

    -- == 3. DETERMINE WINNER ==
    SELECT COUNT(*) INTO v_home_wins
    FROM GameRound
    WHERE game_id = p_game_id AND winner_team_id = v_home_team;

    SELECT COUNT(*) INTO v_away_wins
    FROM GameRound
    WHERE game_id = p_game_id AND winner_team_id = v_away_team;
    
    IF v_home_wins > v_away_wins THEN
        SET v_winner_team_id = v_home_team;
        SET v_loser_team_id = v_away_team;
    ELSE
        SET v_winner_team_id = v_away_team;
        SET v_loser_team_id = v_home_team;
    END IF;

    -- == 4A. TALLY ATTACKER STATS (FIXED) ==
    -- This query parses event_types like 'PLINK_DROP' and 'PLINK_CATCH'
    -- and correctly credits the attacker (player_id) with 'PLINKS'.
    INSERT INTO PlayerSeasonMetric (league_id, season_year, player_id, category_code, metric_value)
    SELECT
        v_league_id,
        v_season_year,
        player_id,
        -- Use CASE to map specific events to general stat categories
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
    FROM RoundEvent
    WHERE game_id = p_game_id
    GROUP BY player_id, stat_category
    HAVING stat_category IS NOT NULL
    ON DUPLICATE KEY UPDATE
        metric_value = metric_value + VALUES(metric_value);

    -- == 4B. TALLY DEFENDER STATS (NEW) ==
    -- This query parses event_types like 'PLINK_DROP' and 'HIT_CATCH'
    -- and correctly credits the defender (opponent_player_id) with 'DROPS' or 'CATCHES'.
    INSERT INTO PlayerSeasonMetric (league_id, season_year, player_id, category_code, metric_value)
    SELECT
        v_league_id,
        v_season_year,
        opponent_player_id AS player_id, -- Credit the defender
        -- Use CASE to map specific events to general stat categories
        CASE
            WHEN event_type LIKE '%_DROP' THEN 'DROPS'
            WHEN event_type LIKE '%_CATCH' THEN 'CATCHES'
            ELSE NULL
        END AS stat_category,
        COUNT(*) AS event_count
    FROM RoundEvent
    WHERE 
        game_id = p_game_id 
        AND opponent_player_id IS NOT NULL -- Only tally events with a defender
    GROUP BY player_id, stat_category
    HAVING stat_category IS NOT NULL
    ON DUPLICATE KEY UPDATE
        metric_value = metric_value + VALUES(metric_value);

    -- == 5. TALLY WINS & LOSSES ==
    INSERT INTO PlayerSeasonMetric (league_id, season_year, player_id, category_code, metric_value)
    SELECT v_league_id, v_season_year, player_id, 'PLAYER_WINS', 1
    FROM TeamMembership
    WHERE team_id = v_winner_team_id
    ON DUPLICATE KEY UPDATE metric_value = metric_value + 1;

    INSERT INTO PlayerSeasonMetric (league_id, season_year, player_id, category_code, metric_value)
    SELECT v_league_id, v_season_year, player_id, 'PLAYER_LOSSES', 1
    FROM TeamMembership
    WHERE team_id = v_loser_team_id
    ON DUPLICATE KEY UPDATE metric_value = metric_value + 1;

    -- == 6. FINALIZE GAME ==
    UPDATE Game SET status = 'Completed' WHERE game_id = p_game_id;
    
    SELECT 'Game finalized and stats tallied successfully.' AS result;

END$$

DELIMITER ;

-- --------------------------------------------------------

--
-- Table structure for table `game`
--

CREATE TABLE `game` (
  `game_id` int(11) NOT NULL,
  `league_id` int(11) NOT NULL,
  `status` varchar(50) NOT NULL,
  `scheduled_at` datetime DEFAULT NULL,
  `home_team` int(11) NOT NULL,
  `away_team` int(11) NOT NULL,
  `playoff_flag` tinyint(1) NOT NULL DEFAULT 0,
  `round_best_of` int(11) NOT NULL DEFAULT 1
) ;

--
-- Dumping data for table `game`
--

INSERT INTO `game` (`game_id`, `league_id`, `status`, `scheduled_at`, `home_team`, `away_team`, `playoff_flag`, `round_best_of`) VALUES
(1, 1, 'Completed', '2025-10-27 19:54:15', 4, 7, 0, 1),
(3, 1, 'Completed', '2025-10-27 20:42:34', 3, 5, 0, 5);

--
-- Triggers `game`
--
DELIMITER $$
CREATE TRIGGER `trg_Game_SameLeague` BEFORE INSERT ON `game` FOR EACH ROW BEGIN
    -- Variable to hold the league_id for each team
    DECLARE home_league_id INT;
    DECLARE away_league_id INT;

    -- Find the league for the home team
    SELECT league_id INTO home_league_id 
    FROM Team 
    WHERE team_id = NEW.home_team;

    -- Find the league for the away team
    SELECT league_id INTO away_league_id 
    FROM Team 
    WHERE team_id = NEW.away_team;

    -- Check if both teams are in the same league as the game
    IF (home_league_id != NEW.league_id) OR (away_league_id != NEW.league_id) THEN
        -- If not, raise an error and prevent the insert
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Teams must belong to the same league as the game.';
    END IF;
END
$$
DELIMITER ;

-- --------------------------------------------------------

--
-- Table structure for table `gameround`
--

CREATE TABLE `gameround` (
  `game_id` int(11) NOT NULL,
  `round_number` int(11) NOT NULL,
  `status` varchar(50) NOT NULL,
  `winner_team_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `gameround`
--

INSERT INTO `gameround` (`game_id`, `round_number`, `status`, `winner_team_id`) VALUES
(1, 1, 'Completed', 4),
(3, 1, 'Completed', 3),
(3, 2, 'Completed', 5),
(3, 3, 'Completed', 3),
(3, 4, 'Completed', 5),
(3, 5, 'Completed', 5);

-- --------------------------------------------------------

--
-- Table structure for table `league`
--

CREATE TABLE `league` (
  `league_id` int(11) NOT NULL,
  `name` varchar(255) NOT NULL,
  `season_year` int(11) NOT NULL,
  `status` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `league`
--

INSERT INTO `league` (`league_id`, `name`, `season_year`, `status`) VALUES
(1, 'Founders Cup', 2025, 'Active');

-- --------------------------------------------------------

--
-- Table structure for table `player`
--

CREATE TABLE `player` (
  `player_id` int(11) NOT NULL,
  `first_name` varchar(255) NOT NULL,
  `last_name` varchar(255) NOT NULL,
  `email` varchar(255) DEFAULT NULL,
  `user_id` int(11) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `player`
--

INSERT INTO `player` (`player_id`, `first_name`, `last_name`, `email`, `user_id`) VALUES
(1, 'Alice', 'Smith', 'p1@example.com', 1),
(2, 'Bob', 'Johnson', 'p2@example.com', 2),
(3, 'Charlie', 'Brown', 'p3@example.com', 3),
(4, 'Diana', 'Miller', 'p4@example.com', 4),
(5, 'Evan', 'White', 'p5@example.com', 5),
(6, 'Fiona', 'Green', 'p6@example.com', 6),
(7, 'George', 'Harris', 'p7@example.com', 7),
(8, 'Hannah', 'Clark', 'p8@example.com', 8),
(9, 'Ian', 'Lewis', 'p9@example.com', 9),
(10, 'Jane', 'Walker', 'p10@example.com', 10),
(11, 'Kyle', 'Hall', 'p11@example.com', 11),
(12, 'Laura', 'Allen', 'p12@example.com', 12),
(13, 'Mike', 'Young', 'p13@example.com', 13),
(14, 'Nina', 'King', 'p14@example.com', 14),
(15, 'Oscar', 'Wright', 'p15@example.com', 15),
(16, 'Penny', 'Scott', 'p16@example.com', 16);

-- --------------------------------------------------------

--
-- Table structure for table `playerseasonmetric`
--

CREATE TABLE `playerseasonmetric` (
  `league_id` int(11) NOT NULL,
  `season_year` int(11) NOT NULL,
  `player_id` int(11) NOT NULL,
  `category_code` varchar(50) NOT NULL,
  `metric_value` decimal(10,2) NOT NULL DEFAULT 0.00
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `playerseasonmetric`
--

INSERT INTO `playerseasonmetric` (`league_id`, `season_year`, `player_id`, `category_code`, `metric_value`) VALUES
(1, 2025, 1, 'DROPS', 0.00),
(1, 2025, 1, 'HITS', 0.00),
(1, 2025, 1, 'PLAYER_LOSSES', 0.00),
(1, 2025, 2, 'DROPS', 0.00),
(1, 2025, 2, 'HITS', 0.00),
(1, 2025, 2, 'PLAYER_LOSSES', 0.00),
(1, 2025, 2, 'PLINKS', 0.00),
(1, 2025, 3, 'CATCHES', 0.00),
(1, 2025, 3, 'DROPS', 0.00),
(1, 2025, 3, 'HITS', 0.00),
(1, 2025, 3, 'MISSES', 0.00),
(1, 2025, 3, 'PLAYER_WINS', 0.00),
(1, 2025, 4, 'CATCHES', 0.00),
(1, 2025, 4, 'DROPS', 0.00),
(1, 2025, 4, 'HITS', 0.00),
(1, 2025, 4, 'PLAYER_WINS', 0.00),
(1, 2025, 4, 'PLINKS', 0.00),
(1, 2025, 5, 'DROPS', 8.00),
(1, 2025, 5, 'HITS', 5.00),
(1, 2025, 5, 'MISSES', 1.00),
(1, 2025, 5, 'PLAYER_LOSSES', 1.00),
(1, 2025, 5, 'PLINKS', 5.00),
(1, 2025, 6, 'DROPS', 8.00),
(1, 2025, 6, 'HITS', 3.00),
(1, 2025, 6, 'PLAYER_LOSSES', 1.00),
(1, 2025, 6, 'PLINKS', 4.00),
(1, 2025, 7, 'DROPS', 2.00),
(1, 2025, 7, 'HITS', 1.00),
(1, 2025, 7, 'MISSES', 1.00),
(1, 2025, 7, 'PLAYER_WINS', 1.00),
(1, 2025, 7, 'PLINKS', 1.00),
(1, 2025, 8, 'DROPS', 2.00),
(1, 2025, 8, 'HITS', 1.00),
(1, 2025, 8, 'PLAYER_WINS', 1.00),
(1, 2025, 8, 'PLINKS', 2.00),
(1, 2025, 9, 'CATCHES', 1.00),
(1, 2025, 9, 'DROPS', 9.00),
(1, 2025, 9, 'HITS', 3.00),
(1, 2025, 9, 'PLAYER_WINS', 1.00),
(1, 2025, 9, 'PLINKS', 5.00),
(1, 2025, 9, 'PLUNKS', 1.00),
(1, 2025, 10, 'DROPS', 7.00),
(1, 2025, 10, 'HITS', 3.00),
(1, 2025, 10, 'PLAYER_WINS', 1.00),
(1, 2025, 10, 'PLINKS', 5.00),
(1, 2025, 13, 'DROPS', 2.00),
(1, 2025, 13, 'HITS', 2.00),
(1, 2025, 13, 'PLAYER_LOSSES', 1.00),
(1, 2025, 13, 'PLINKS', 1.00),
(1, 2025, 14, 'CATCHES', 1.00),
(1, 2025, 14, 'DROPS', 2.00),
(1, 2025, 14, 'HITS', 1.00),
(1, 2025, 14, 'PLAYER_LOSSES', 1.00);

-- --------------------------------------------------------

--
-- Table structure for table `roleassignment`
--

CREATE TABLE `roleassignment` (
  `user_id` int(11) NOT NULL,
  `league_id` int(11) NOT NULL,
  `role` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `roleassignment`
--

INSERT INTO `roleassignment` (`user_id`, `league_id`, `role`) VALUES
(1, 1, 'Commissioner');

-- --------------------------------------------------------

--
-- Table structure for table `roundevent`
--

CREATE TABLE `roundevent` (
  `event_id` int(11) NOT NULL,
  `game_id` int(11) NOT NULL,
  `round_number` int(11) NOT NULL,
  `sequence_number` int(11) NOT NULL,
  `player_team_id` int(11) NOT NULL,
  `player_id` int(11) NOT NULL,
  `opponent_team_id` int(11) DEFAULT NULL,
  `opponent_player_id` int(11) DEFAULT NULL,
  `event_type` varchar(50) NOT NULL,
  `player_lp_delta` int(11) NOT NULL DEFAULT 0,
  `opponent_lp_delta` int(11) NOT NULL DEFAULT 0,
  `notes` text DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `roundevent`
--

INSERT INTO `roundevent` (`event_id`, `game_id`, `round_number`, `sequence_number`, `player_team_id`, `player_id`, `opponent_team_id`, `opponent_player_id`, `event_type`, `player_lp_delta`, `opponent_lp_delta`, `notes`) VALUES
(1, 1, 1, 1, 4, 7, 7, 13, 'HIT_DROP', 1, 0, NULL),
(2, 1, 1, 2, 7, 13, 4, 8, 'HIT_DROP', 1, 0, NULL),
(4, 1, 1, 3, 4, 8, 7, 14, 'PLINK_CATCH', 1, 0, NULL),
(5, 1, 1, 4, 7, 14, 4, 7, 'HIT_DROP', 1, 0, NULL),
(6, 1, 1, 5, 4, 7, 7, 13, 'PLINK_DROP', 2, 0, NULL),
(7, 1, 1, 6, 7, 13, 4, 8, 'PLINK_DROP', 2, 0, NULL),
(8, 1, 1, 7, 4, 8, 7, 14, 'HIT_DROP', 1, 0, NULL),
(10, 1, 1, 8, 4, 7, NULL, NULL, 'MISS', 0, 0, NULL),
(11, 1, 1, 9, 7, 13, 4, 7, 'HIT_DROP', 1, 0, NULL),
(12, 1, 1, 10, 4, 8, 7, 14, 'PLINK_DROP', 2, 0, NULL),
(23, 3, 1, 1, 3, 5, 5, 9, 'PLINK_DROP', 2, 0, NULL),
(24, 3, 1, 2, 5, 9, 3, 6, 'HIT_DROP', 1, 0, NULL),
(25, 3, 1, 3, 3, 6, 5, 10, 'HIT_DROP', 1, 0, NULL),
(26, 3, 1, 4, 5, 10, 3, 5, 'PLINK_DROP', 2, 0, NULL),
(27, 3, 1, 5, 3, 5, 5, 9, 'PLINK_DROP', 2, 0, NULL),
(28, 3, 1, 6, 5, 9, 3, 6, 'HIT_DROP', 1, 0, NULL),
(29, 3, 1, 7, 3, 6, 5, 10, 'PLINK_DROP', 2, 0, NULL),
(30, 3, 2, 1, 5, 9, 3, 5, 'PLINK_DROP', 2, 0, NULL),
(31, 3, 2, 2, 3, 5, 5, 10, 'HIT_DROP', 1, 0, NULL),
(32, 3, 2, 3, 5, 10, 3, 6, 'HIT_DROP', 1, 0, NULL),
(33, 3, 2, 4, 3, 6, 5, 9, 'PLINK_DROP', 2, 0, NULL),
(34, 3, 2, 5, 5, 9, 3, 5, 'PLINK_DROP', 2, 0, NULL),
(35, 3, 2, 6, 3, 5, 5, 10, 'PLINK_DROP', 2, 0, NULL),
(36, 3, 2, 7, 5, 10, 3, 6, 'PLINK_DROP', 2, 0, NULL),
(37, 3, 3, 1, 3, 5, 5, 9, 'PLINK_DROP', 2, 0, NULL),
(38, 3, 3, 2, 5, 9, 3, 6, 'PLINK_DROP', 2, 0, NULL),
(39, 3, 3, 3, 3, 6, 5, 10, 'PLINK_DROP', 2, 0, NULL),
(40, 3, 3, 4, 5, 10, 3, 5, 'PLINK_DROP', 2, 0, NULL),
(41, 3, 3, 5, 3, 5, 5, 9, 'HIT_DROP', 1, 0, NULL),
(42, 3, 3, 6, 5, 9, 3, 6, 'HIT_DROP', 1, 0, NULL),
(43, 3, 3, 7, 3, 6, 5, 10, 'HIT_DROP', 1, 0, NULL),
(44, 3, 3, 8, 5, 10, 3, 5, 'HIT_DROP', 1, 0, NULL),
(45, 3, 3, 9, 3, 5, 5, 9, 'PLINK_DROP', 2, 0, NULL),
(46, 3, 3, 10, 3, 6, 5, 10, 'PLINK_DROP', 2, 0, NULL),
(47, 3, 4, 1, 5, 9, NULL, NULL, 'PLUNK', 5, 0, NULL),
(48, 3, 4, 2, 3, 5, 5, 9, 'HIT_DROP', 1, 0, NULL),
(49, 3, 4, 3, 5, 10, 3, 6, 'PLINK_DROP', 2, 0, NULL),
(50, 3, 4, 4, 3, 6, 5, 10, 'HIT_DROP', 1, 0, NULL),
(51, 3, 4, 5, 3, 5, 5, 9, 'HIT_CATCH', 0, 0, NULL),
(52, 3, 4, 6, 3, 5, 5, 9, 'HIT_DROP', 1, 0, NULL),
(53, 3, 5, 1, 5, 9, 3, 5, 'PLINK_DROP', 2, 0, NULL),
(54, 3, 5, 2, 5, 10, 3, 6, 'PLINK_DROP', 2, 0, NULL),
(55, 3, 5, 3, 3, 5, 5, 9, 'MISS', 0, 0, NULL),
(56, 3, 5, 4, 5, 9, 3, 5, 'PLINK_DROP', 2, 0, NULL),
(57, 3, 5, 5, 5, 10, 3, 6, 'HIT_DROP', 1, 0, NULL);

-- --------------------------------------------------------

--
-- Table structure for table `roundscore`
--

CREATE TABLE `roundscore` (
  `game_id` int(11) NOT NULL,
  `round_number` int(11) NOT NULL,
  `team_id` int(11) NOT NULL,
  `little_points` int(11) NOT NULL DEFAULT 0,
  `big_point_awarded` tinyint(1) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `roundscore`
--

INSERT INTO `roundscore` (`game_id`, `round_number`, `team_id`, `little_points`, `big_point_awarded`) VALUES
(1, 1, 4, 7, 1),
(1, 1, 7, 5, 0),
(3, 1, 3, 7, 1),
(3, 1, 5, 4, 0),
(3, 2, 3, 5, 0),
(3, 2, 5, 7, 1),
(3, 3, 3, 8, 1),
(3, 3, 5, 6, 0),
(3, 4, 3, 3, 0),
(3, 4, 5, 7, 1),
(3, 5, 3, 0, 0),
(3, 5, 5, 7, 1);

-- --------------------------------------------------------

--
-- Table structure for table `seasonaward`
--

CREATE TABLE `seasonaward` (
  `league_id` int(11) NOT NULL,
  `season_year` int(11) NOT NULL,
  `category_code` varchar(50) NOT NULL,
  `winner_player_id` int(11) NOT NULL,
  `metric_value` decimal(10,2) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `seasonaward`
--

INSERT INTO `seasonaward` (`league_id`, `season_year`, `category_code`, `winner_player_id`, `metric_value`) VALUES
(1, 2025, 'CATCHES', 14, 1.00),
(1, 2025, 'DROPS', 7, 2.00),
(1, 2025, 'HITS', 13, 2.00),
(1, 2025, 'MISSES', 7, 1.00),
(1, 2025, 'PLAYER_LOSSES', 14, 1.00),
(1, 2025, 'PLAYER_WINS', 8, 1.00),
(1, 2025, 'PLINKS', 8, 2.00);

-- --------------------------------------------------------

--
-- Table structure for table `seasonstatcategory`
--

CREATE TABLE `seasonstatcategory` (
  `category_code` varchar(50) NOT NULL,
  `display_name` varchar(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `seasonstatcategory`
--

INSERT INTO `seasonstatcategory` (`category_code`, `display_name`) VALUES
('CATCHES', 'Total Catches (Defense)'),
('DROPS', 'Total Drops (Defense)'),
('HITS', 'Total Hits (on Table)'),
('KICKED', 'Total Times Kicked'),
('KICKS', 'Total Kicks'),
('MISSES', 'Total Misses (Offense)'),
('PLAYER_LOSSES', 'Player Game Losses'),
('PLAYER_WINS', 'Player Game Wins'),
('PLINKS', 'Total Plinks (on Glass)'),
('PLUNKS', 'Total Plunks'),
('SELF_FG', 'Self Field Goals');

-- --------------------------------------------------------

--
-- Table structure for table `team`
--

CREATE TABLE `team` (
  `team_id` int(11) NOT NULL,
  `league_id` int(11) NOT NULL,
  `team_name` varchar(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `team`
--

INSERT INTO `team` (`team_id`, `league_id`, `team_name`) VALUES
(4, 1, 'Cup Crusaders'),
(2, 1, 'Dye Hard'),
(8, 1, 'Liquid Gold'),
(5, 1, 'Pitch Perfect'),
(7, 1, 'Rolling Thunder'),
(1, 1, 'Sink or Swim'),
(6, 1, 'Table Titans'),
(3, 1, 'The Tossers');

-- --------------------------------------------------------

--
-- Table structure for table `teammembership`
--

CREATE TABLE `teammembership` (
  `team_id` int(11) NOT NULL,
  `player_id` int(11) NOT NULL,
  `active` tinyint(1) NOT NULL DEFAULT 1,
  `joined_at` datetime NOT NULL DEFAULT current_timestamp(),
  `left_at` datetime DEFAULT NULL
) ;

--
-- Dumping data for table `teammembership`
--

INSERT INTO `teammembership` (`team_id`, `player_id`, `active`, `joined_at`, `left_at`) VALUES
(1, 1, 1, '2025-10-27 19:36:24', NULL),
(1, 2, 1, '2025-10-27 19:36:24', NULL),
(2, 3, 1, '2025-10-27 19:36:24', NULL),
(2, 4, 1, '2025-10-27 19:36:24', NULL),
(3, 5, 1, '2025-10-27 19:36:24', NULL),
(3, 6, 1, '2025-10-27 19:36:24', NULL),
(4, 7, 1, '2025-10-27 19:36:24', NULL),
(4, 8, 1, '2025-10-27 19:36:24', NULL),
(5, 9, 1, '2025-10-27 19:36:24', NULL),
(5, 10, 1, '2025-10-27 19:36:24', NULL),
(6, 11, 1, '2025-10-27 19:36:24', NULL),
(6, 12, 1, '2025-10-27 19:36:24', NULL),
(7, 13, 1, '2025-10-27 19:36:24', NULL),
(7, 14, 1, '2025-10-27 19:36:24', NULL),
(8, 15, 1, '2025-10-27 19:36:24', NULL),
(8, 16, 1, '2025-10-27 19:36:24', NULL);

-- --------------------------------------------------------

--
-- Table structure for table `useraccount`
--

CREATE TABLE `useraccount` (
  `user_id` int(11) NOT NULL,
  `name` varchar(255) NOT NULL,
  `email` varchar(255) NOT NULL,
  `password_hash` varchar(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

--
-- Dumping data for table `useraccount`
--

INSERT INTO `useraccount` (`user_id`, `name`, `email`, `password_hash`) VALUES
(1, 'Alice Smith', 'p1@example.com', 'placeholder_hash'),
(2, 'Bob Johnson', 'p2@example.com', 'placeholder_hash'),
(3, 'Charlie Brown', 'p3@example.com', 'placeholder_hash'),
(4, 'Diana Miller', 'p4@example.com', 'placeholder_hash'),
(5, 'Evan White', 'p5@example.com', 'placeholder_hash'),
(6, 'Fiona Green', 'p6@example.com', 'placeholder_hash'),
(7, 'George Harris', 'p7@example.com', 'placeholder_hash'),
(8, 'Hannah Clark', 'p8@example.com', 'placeholder_hash'),
(9, 'Ian Lewis', 'p9@example.com', 'placeholder_hash'),
(10, 'Jane Walker', 'p10@example.com', 'placeholder_hash'),
(11, 'Kyle Hall', 'p11@example.com', 'placeholder_hash'),
(12, 'Laura Allen', 'p12@example.com', 'placeholder_hash'),
(13, 'Mike Young', 'p13@example.com', 'placeholder_hash'),
(14, 'Nina King', 'p14@example.com', 'placeholder_hash'),
(15, 'Oscar Wright', 'p15@example.com', 'placeholder_hash'),
(16, 'Penny Scott', 'p16@example.com', 'placeholder_hash');

--
-- Indexes for dumped tables
--

--
-- Indexes for table `game`
--
ALTER TABLE `game`
  ADD PRIMARY KEY (`game_id`),
  ADD KEY `league_id` (`league_id`),
  ADD KEY `home_team` (`home_team`),
  ADD KEY `away_team` (`away_team`);

--
-- Indexes for table `gameround`
--
ALTER TABLE `gameround`
  ADD PRIMARY KEY (`game_id`,`round_number`),
  ADD KEY `winner_team_id` (`winner_team_id`);

--
-- Indexes for table `league`
--
ALTER TABLE `league`
  ADD PRIMARY KEY (`league_id`),
  ADD UNIQUE KEY `name` (`name`,`season_year`);

--
-- Indexes for table `player`
--
ALTER TABLE `player`
  ADD PRIMARY KEY (`player_id`),
  ADD UNIQUE KEY `email` (`email`),
  ADD UNIQUE KEY `user_id` (`user_id`);

--
-- Indexes for table `playerseasonmetric`
--
ALTER TABLE `playerseasonmetric`
  ADD PRIMARY KEY (`league_id`,`season_year`,`player_id`,`category_code`),
  ADD KEY `player_id` (`player_id`),
  ADD KEY `category_code` (`category_code`);

--
-- Indexes for table `roleassignment`
--
ALTER TABLE `roleassignment`
  ADD PRIMARY KEY (`user_id`,`league_id`,`role`),
  ADD KEY `league_id` (`league_id`);

--
-- Indexes for table `roundevent`
--
ALTER TABLE `roundevent`
  ADD PRIMARY KEY (`event_id`),
  ADD UNIQUE KEY `game_id` (`game_id`,`round_number`,`sequence_number`),
  ADD KEY `player_team_id` (`player_team_id`),
  ADD KEY `player_id` (`player_id`),
  ADD KEY `opponent_team_id` (`opponent_team_id`),
  ADD KEY `opponent_player_id` (`opponent_player_id`);

--
-- Indexes for table `roundscore`
--
ALTER TABLE `roundscore`
  ADD PRIMARY KEY (`game_id`,`round_number`,`team_id`),
  ADD KEY `team_id` (`team_id`);

--
-- Indexes for table `seasonaward`
--
ALTER TABLE `seasonaward`
  ADD PRIMARY KEY (`league_id`,`season_year`,`category_code`),
  ADD KEY `category_code` (`category_code`),
  ADD KEY `winner_player_id` (`winner_player_id`);

--
-- Indexes for table `seasonstatcategory`
--
ALTER TABLE `seasonstatcategory`
  ADD PRIMARY KEY (`category_code`);

--
-- Indexes for table `team`
--
ALTER TABLE `team`
  ADD PRIMARY KEY (`team_id`),
  ADD UNIQUE KEY `league_id` (`league_id`,`team_name`);

--
-- Indexes for table `teammembership`
--
ALTER TABLE `teammembership`
  ADD PRIMARY KEY (`team_id`,`player_id`),
  ADD KEY `player_id` (`player_id`);

--
-- Indexes for table `useraccount`
--
ALTER TABLE `useraccount`
  ADD PRIMARY KEY (`user_id`),
  ADD UNIQUE KEY `email` (`email`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `game`
--
ALTER TABLE `game`
  MODIFY `game_id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT for table `league`
--
ALTER TABLE `league`
  MODIFY `league_id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT for table `player`
--
ALTER TABLE `player`
  MODIFY `player_id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=17;

--
-- AUTO_INCREMENT for table `roundevent`
--
ALTER TABLE `roundevent`
  MODIFY `event_id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=58;

--
-- AUTO_INCREMENT for table `team`
--
ALTER TABLE `team`
  MODIFY `team_id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=9;

--
-- AUTO_INCREMENT for table `useraccount`
--
ALTER TABLE `useraccount`
  MODIFY `user_id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=17;

--
-- Constraints for dumped tables
--

--
-- Constraints for table `game`
--
ALTER TABLE `game`
  ADD CONSTRAINT `game_ibfk_1` FOREIGN KEY (`league_id`) REFERENCES `league` (`league_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `game_ibfk_2` FOREIGN KEY (`home_team`) REFERENCES `team` (`team_id`),
  ADD CONSTRAINT `game_ibfk_3` FOREIGN KEY (`away_team`) REFERENCES `team` (`team_id`);

--
-- Constraints for table `gameround`
--
ALTER TABLE `gameround`
  ADD CONSTRAINT `gameround_ibfk_1` FOREIGN KEY (`game_id`) REFERENCES `game` (`game_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `gameround_ibfk_2` FOREIGN KEY (`winner_team_id`) REFERENCES `team` (`team_id`);

--
-- Constraints for table `player`
--
ALTER TABLE `player`
  ADD CONSTRAINT `fk_player_useraccount` FOREIGN KEY (`user_id`) REFERENCES `useraccount` (`user_id`) ON DELETE SET NULL;

--
-- Constraints for table `playerseasonmetric`
--
ALTER TABLE `playerseasonmetric`
  ADD CONSTRAINT `playerseasonmetric_ibfk_1` FOREIGN KEY (`league_id`) REFERENCES `league` (`league_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `playerseasonmetric_ibfk_2` FOREIGN KEY (`player_id`) REFERENCES `player` (`player_id`),
  ADD CONSTRAINT `playerseasonmetric_ibfk_3` FOREIGN KEY (`category_code`) REFERENCES `seasonstatcategory` (`category_code`);

--
-- Constraints for table `roleassignment`
--
ALTER TABLE `roleassignment`
  ADD CONSTRAINT `roleassignment_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `useraccount` (`user_id`),
  ADD CONSTRAINT `roleassignment_ibfk_2` FOREIGN KEY (`league_id`) REFERENCES `league` (`league_id`) ON DELETE CASCADE;

--
-- Constraints for table `roundevent`
--
ALTER TABLE `roundevent`
  ADD CONSTRAINT `roundevent_ibfk_1` FOREIGN KEY (`game_id`,`round_number`) REFERENCES `gameround` (`game_id`, `round_number`) ON DELETE CASCADE,
  ADD CONSTRAINT `roundevent_ibfk_2` FOREIGN KEY (`player_team_id`) REFERENCES `team` (`team_id`),
  ADD CONSTRAINT `roundevent_ibfk_3` FOREIGN KEY (`player_id`) REFERENCES `player` (`player_id`),
  ADD CONSTRAINT `roundevent_ibfk_4` FOREIGN KEY (`opponent_team_id`) REFERENCES `team` (`team_id`),
  ADD CONSTRAINT `roundevent_ibfk_5` FOREIGN KEY (`opponent_player_id`) REFERENCES `player` (`player_id`);

--
-- Constraints for table `roundscore`
--
ALTER TABLE `roundscore`
  ADD CONSTRAINT `roundscore_ibfk_1` FOREIGN KEY (`game_id`,`round_number`) REFERENCES `gameround` (`game_id`, `round_number`) ON DELETE CASCADE,
  ADD CONSTRAINT `roundscore_ibfk_2` FOREIGN KEY (`team_id`) REFERENCES `team` (`team_id`);

--
-- Constraints for table `seasonaward`
--
ALTER TABLE `seasonaward`
  ADD CONSTRAINT `seasonaward_ibfk_1` FOREIGN KEY (`league_id`) REFERENCES `league` (`league_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `seasonaward_ibfk_2` FOREIGN KEY (`category_code`) REFERENCES `seasonstatcategory` (`category_code`),
  ADD CONSTRAINT `seasonaward_ibfk_3` FOREIGN KEY (`winner_player_id`) REFERENCES `player` (`player_id`);

--
-- Constraints for table `team`
--
ALTER TABLE `team`
  ADD CONSTRAINT `team_ibfk_1` FOREIGN KEY (`league_id`) REFERENCES `league` (`league_id`) ON DELETE CASCADE;

--
-- Constraints for table `teammembership`
--
ALTER TABLE `teammembership`
  ADD CONSTRAINT `teammembership_ibfk_1` FOREIGN KEY (`team_id`) REFERENCES `team` (`team_id`) ON DELETE CASCADE,
  ADD CONSTRAINT `teammembership_ibfk_2` FOREIGN KEY (`player_id`) REFERENCES `player` (`player_id`);
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
