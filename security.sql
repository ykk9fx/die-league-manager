-- Least privilege DB user for local demo
DROP USER IF EXISTS 'app_user'@'localhost';
CREATE USER 'app_user'@'localhost' IDENTIFIED BY 'app_pw_123';

GRANT SELECT, INSERT, UPDATE, DELETE ON die_league_db.* TO 'app_user'@'localhost';

GRANT EXECUTE ON PROCEDURE die_league_db.sp_TallyAndFinalizeGame TO 'app_user'@'localhost';
FLUSH PRIVILEGES;
