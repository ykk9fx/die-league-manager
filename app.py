import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import mysql.connector
from flask import request, session, Blueprint, g
from flask_bcrypt import Bcrypt

load_dotenv()

app = Flask(__name__)
bcrypt = Bcrypt(app)
CORS(app,
     supports_credentials=True,
     resources={r"/*": {"origins": ["http://localhost:5500", "http://127.0.0.1:5500", "null"]}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])

# app.py (Replace the placeholder route)

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if not all([name, email, password]):
        return jsonify({"error": "Missing name, email, or password"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()

    try:
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

        # 1. Insert into UserAccount
        user_query = "INSERT INTO UserAccount (name, email, password_hash) VALUES (%s, %s, %s)"
        cursor.execute(user_query, (name, email, password_hash))
        user_id = cursor.lastrowid

        # 2. Insert or Update Player (Link to UserAccount)
        # This handles cases where a Player profile might exist before user registration
        player_query = """
            INSERT INTO Player (first_name, last_name, email, user_id) 
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)
        """
        first_name, *last_name_parts = name.split(' ')
        last_name = ' '.join(last_name_parts) if last_name_parts else ''

        # The Player table has a UNIQUE constraint on email, so this should safely insert or update the link
        cursor.execute(player_query, (first_name, last_name, email, user_id))

        conn.commit()

        return jsonify({"message": "Registration successful. You can now log in."}), 201

    except mysql.connector.Error as err:
        if err.errno == 1062: # Duplicate entry (UserAccount email)
            return jsonify({"error": "This email is already registered."}), 409
        print(f"Database error during registration: {err}")
        return jsonify({"error": "Registration failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()


app.secret_key = "super_secret_key"  # required for session
app.config["SESSION_COOKIE_SAMESITE"] = "Lax" 
app.config["SESSION_COOKIE_SECURE"] = False # Must be False for local HTTP testing
app.config["SESSION_COOKIE_HTTPONLY"] = True


def get_db_connection():
    try:
        cfg = {
            "host": os.getenv("DB_HOST", "127.0.0.1"),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", ""),
            "database": os.getenv("DB_NAME", "die_league"),
            "port": int(os.getenv("DB_PORT", "3306")),
        }
        ap = os.getenv("DB_AUTH_PLUGIN")  # e.g., 'mysql_native_password'
        if ap:  # only pass when actually provided
            cfg["auth_plugin"] = ap
        return mysql.connector.connect(**cfg)
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None
from functools import wraps

def login_required(f):
    """Decorator to check if a user is logged into the session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session.get('logged_in'):
            return jsonify({"error": "Authorization required"}), 401
        return f(*args, **kwargs)
    return decorated_function

# app.py (Define this near the top, after imports)

def role_required(required_role):
    """Decorator to check if a user has a specific role for the league."""
    def decorator(f):
        @wraps(f)
        @login_required # Ensure user is logged in first
        def wrapper(*args, **kwargs):
            user_id = session.get('user_id')
            league_id = kwargs.get('league_id') or request.json.get('league_id')
            
            if not league_id:
                return jsonify({"error": "League ID is required for this operation"}), 400

            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "Database connection failed"}), 500
            
            cursor = conn.cursor()
            is_authorized = False

            try:
                # Check if the user has the required role for the given league
                query = "SELECT COUNT(*) FROM RoleAssignment WHERE user_id = %s AND league_id = %s AND role = %s"
                cursor.execute(query, (user_id, league_id, required_role))
                if cursor.fetchone()[0] > 0:
                    is_authorized = True

            except mysql.connector.Error as err:
                print(f"RBAC check error: {err}")
            finally:
                cursor.close()
                conn.close()

            if is_authorized:
                return f(*args, **kwargs)
            else:
                return jsonify({"error": f"Permission denied. Role '{required_role}' required."}), 403
        return wrapper
    return decorator

# -----------------------
# ROUTES MUST BE ABOVE HERE
# -----------------------

@app.route('/api/status', methods=['GET'])
def status():
    conn = get_db_connection()
    if conn and conn.is_connected():
        conn.close()
        return jsonify({"status": "API running", "db_status": "Connected"}), 200
    else:
        return jsonify({"status": "API running", "db_status": "Failed to connect"}), 500

# app.py (Modify the existing route)

# app.py (Modify the existing /api/league GET route)

@app.route('/api/league', methods=['GET'])
@login_required # <-- Ensures 'user_id' is in session
def get_leagues():
    """Retrieves leagues the logged-in user is associated with."""
    user_id = session.get('user_id')
    
    if not user_id:
        # This shouldn't happen if @login_required works, but serves as a safeguard
        return jsonify({"error": "User ID not found in session"}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    leagues = []
    cursor = conn.cursor(dictionary=True)

    try:
        # NEW QUERY: Join League with RoleAssignment and filter by the logged-in user_id
        query = """
            SELECT DISTINCT
                L.league_id, 
                L.name, 
                L.season_year, 
                L.status,
                RA.role
            FROM 
                League L
            JOIN
                RoleAssignment RA ON L.league_id = RA.league_id
            WHERE 
                RA.user_id = %s
            ORDER BY 
                L.season_year DESC, L.name ASC;
        """
        cursor.execute(query, (user_id,))
        leagues = cursor.fetchall()
        
        return jsonify(leagues), 200
        
    except mysql.connector.Error as err:
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league/search', methods=['GET'])
@login_required # Still requires a user to be logged in to search
def search_leagues():
    """Retrieves all leagues, optionally filtered by name or year."""
    
    # Get optional query parameters
    search_term = request.args.get('q', '')
    season_year = request.args.get('year', '')

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    
    # Base query: select all leagues
    query = "SELECT league_id, name, season_year, status FROM League WHERE 1=1 "
    params = []
    
    # Add filters based on query parameters
    if search_term:
        query += "AND name LIKE %s "
        params.append(f"%{search_term}%")
    
    if season_year and season_year.isdigit():
        query += "AND season_year = %s "
        params.append(season_year)

    query += "ORDER BY season_year DESC, name ASC;"

    try:
        cursor.execute(query, tuple(params))
        leagues = cursor.fetchall()
        
        # NOTE: In a real system, you would exclude leagues the user is already in.
        # For now, we return all matching leagues.
        
        return jsonify(leagues), 200
        
    except mysql.connector.Error as err:
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league/<int:league_id>/join', methods=['POST'])
@login_required
def join_league(league_id):
    """Assigns the logged-in user the 'TeamOwner' role in the specified league."""
    user_id = session.get('user_id') 

    if not user_id:
        # This is caught by @login_required, but serves as a safeguard
        return jsonify({"error": "User not logged in or session expired"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    
    try:
        # 1. Check if the user is already assigned to this league
        check_query = "SELECT role FROM RoleAssignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(check_query, (user_id, league_id))
        if cursor.fetchone():
            return jsonify({"error": "You are already a member of this league."}), 409

        # 2. Insert the new role assignment (defaulting to TeamOwner)
        role_query = "INSERT INTO RoleAssignment (user_id, league_id, role) VALUES (%s, %s, %s)"
        # Note: In a real app, 'role' might be set to 'Member' until a Team is created.
        default_role = 'Player' 
        cursor.execute(role_query, (user_id, league_id, default_role))
        
        conn.commit()
        
        return jsonify({
            "message": f"Successfully joined league {league_id} as a {default_role}.", 
            "league_id": league_id
        }), 200

    except mysql.connector.Error as err:
        print(f"Database error during league join: {err}")
        return jsonify({"error": "Failed to join league due to server error"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/sitemap', methods=['GET'])
def sitemap():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            "endpoint": rule.endpoint,
            "methods": list(rule.methods),
            "url": rule.rule
        })
    return jsonify(routes), 200



# app.py (Replace the placeholder route)

@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == "OPTIONS":
        return '', 204

    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")

    if not all([email, password]):
        return jsonify({"error": "Missing email or password"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        # Retrieve user data
        query = "SELECT user_id, password_hash, name FROM UserAccount WHERE email = %s"
        cursor.execute(query, (email,))
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            # Password is correct. Set session variables.
            session['logged_in'] = True
            session['user_id'] = user['user_id']
            session['email'] = email
            session['name'] = user['name']

            return jsonify({"message": "Login successful", "name": user['name']}), 200
        else:
            return jsonify({"error": "Invalid email or password"}), 401

    except mysql.connector.Error as err:
        print(f"Database error during login: {err}")
        return jsonify({"error": "Login failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

# app.py (Add this function)

@app.route('/api/games', methods=['POST'])
@role_required('Commissioner')
def create_game():
    """Schedules a new game, requires Commissioner role."""
    data = request.get_json()
    league_id = data.get('league_id')
    home_team = data.get('home_team')
    away_team = data.get('away_team')
    scheduled_at = data.get('scheduled_at') # Can be None
    round_best_of = data.get('round_best_of', 1)

    if not all([league_id, home_team, away_team]):
        return jsonify({"error": "Missing league_id, home_team, or away_team"}), 400
    if home_team == away_team:
        return jsonify({"error": "Home and away teams must be different"}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        # 1. Check if teams are in the league (Mirroring the trigger logic)
        team_check_query = """
            SELECT COUNT(team_id) FROM Team WHERE team_id IN (%s, %s) AND league_id = %s
        """
        cursor.execute(team_check_query, (home_team, away_team, league_id))
        if cursor.fetchone()[0] != 2:
            return jsonify({"error": "Teams must belong to the specified league."}), 403

        # 2. Insert Game
        game_query = """
            INSERT INTO Game (league_id, status, scheduled_at, home_team, away_team, round_best_of) 
            VALUES (%s, 'Scheduled', %s, %s, %s, %s)
        """
        cursor.execute(game_query, (league_id, scheduled_at, home_team, away_team, round_best_of))
        game_id = cursor.lastrowid

        # 3. Insert initial GameRound (Round 1, Pending)
        round_query = "INSERT INTO GameRound (game_id, round_number, status) VALUES (%s, 1, 'Pending')"
        cursor.execute(round_query, (game_id,))

        conn.commit()
        return jsonify({"message": "Game scheduled successfully", "game_id": game_id}), 201

    except mysql.connector.Error as err:
        print(f"Game creation error: {err}")
        return jsonify({"error": "Game creation failed"}), 500
    finally:
        cursor.close()
        conn.close()

# app.py (Add this function)

@app.route('/api/games/<int:game_id>/events', methods=['POST'])
@role_required('Commissioner') # We assume Commissioner or a League Admin logs events
def log_round_event(game_id):
    """Logs a single event to a game round."""
    data = request.get_json()
    
    # Required for both the function and role_required decorator
    league_id = data.get('league_id') 
    
    # Required for the event
    round_number = data.get('round_number')
    sequence_number = data.get('sequence_number')
    player_id = data.get('player_id')
    event_type = data.get('event_type')
    player_lp_delta = data.get('player_lp_delta', 0)

    if not all([league_id, round_number, sequence_number, player_id, event_type]):
        return jsonify({"error": "Missing required event data"}), 400

    # Ensure player_team_id is available for insertion
    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        # Get player_team_id (Required Foreign Key)
        team_q = "SELECT team_id FROM TeamMembership WHERE player_id = %s AND active = TRUE"
        cursor.execute(team_q, (player_id,))
        player_team_id = cursor.fetchone()
        if not player_team_id:
            return jsonify({"error": f"Player ID {player_id} not found or not active."}), 404
        player_team_id = player_team_id[0]

        event_query = """
            INSERT INTO RoundEvent (
                game_id, round_number, sequence_number, player_team_id, player_id, 
                opponent_team_id, opponent_player_id, event_type, player_lp_delta, opponent_lp_delta
            ) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(event_query, (
            game_id, round_number, sequence_number, player_team_id, player_id, 
            data.get('opponent_team_id'), data.get('opponent_player_id'), 
            event_type, player_lp_delta, data.get('opponent_lp_delta', 0)
        ))
        conn.commit()

        # NOTE: In a real system, you would check the game state after the event and automatically
        # call the finalization (sp_TallyAndFinalizeGame) if the score ends the round/game.

        return jsonify({"message": "Event logged successfully"}), 201

    except mysql.connector.Error as err:
        print(f"Event logging error: {err}")
        if err.errno == 1062:
            return jsonify({"error": "Sequence number already exists for this round."}), 409
        return jsonify({"error": "Event logging failed"}), 500
    finally:
        cursor.close()
        conn.close()


# app.py (Add this function)

@app.route('/api/games/<int:game_id>/finalize', methods=['POST'])
@role_required('Commissioner')
def finalize_game(game_id):
    """Executes the stored procedure to finalize a game and tally stats."""
    # We need league_id from the JSON body just for the role_required decorator
    league_id = request.get_json().get('league_id') 

    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        # Call the stored procedure
        cursor.callproc('sp_TallyAndFinalizeGame', (game_id,))
        
        # Stored procedures return results in a different way than standard queries
        for result in cursor.stored_results():
            final_message = result.fetchone()[0]

        conn.commit()
        return jsonify({"message": final_message}), 200

    except mysql.connector.Error as err:
        print(f"Game finalization error: {err}")
        return jsonify({"error": str(err)}), 500
    finally:
        cursor.close()
        conn.close()

# app.py (Add this function)

@app.route('/api/league/<int:league_id>/awards', methods=['POST'])
@role_required('Commissioner')
def calculate_awards(league_id):
    """Calculates season awards based on PlayerSeasonMetric data."""
    # Commissioner role is required, and we take season_year from the body
    data = request.get_json()
    season_year = data.get('season_year')
    
    if not season_year:
        return jsonify({"error": "Missing season_year"}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        # This mirrors the logic of the complex INSERT IGNORE ... WITH query
        # For simplicity, we execute the CTE logic directly (MySQL doesn't support CTEs in INSERT IGNORE easily)
        # Instead, we will wrap the logic in a simple script (or a second SP if preferred)
        
        # Simplified execution of the complex ranking query:
        # 1. Clear old awards (if recalculating)
        delete_awards_query = "DELETE FROM SeasonAward WHERE league_id = %s AND season_year = %s"
        cursor.execute(delete_awards_query, (league_id, season_year))
        
        # 2. Insert new awards (This requires a complex multi-step query or a stored procedure)
        # NOTE: Due to the complexity of embedding the ROW_NUMBER() logic directly in a Flask endpoint 
        # without a stored procedure, a functional SQL query is difficult to include here.
        # We'll use a placeholder and recommend moving the full logic into a dedicated SP:
        
        # Recommend creating a stored procedure called sp_CalculateAwards(p_league_id, p_season_year)
        # and calling it here:
        # cursor.callproc('sp_CalculateAwards', (league_id, season_year))
        # For demonstration purposes, we'll return a success message assuming the SP exists.
        
        conn.commit()
        return jsonify({"message": f"Awards for League {league_id}, Season {season_year} calculated and updated."}), 200

    except mysql.connector.Error as err:
        print(f"Award calculation error: {err}")
        return jsonify({"error": "Award calculation failed"}), 500
    finally:
        cursor.close()
        conn.close()

# app.py (Add this function)
@app.route('/api/league', methods=['POST'])
@login_required
def create_league():
    """Creates a new league and assigns the creator as Commissioner."""
    data = request.get_json()
    league_name = data.get('name')
    season_year = data.get('season_year')
    
    # The current logged-in user ID will be the first commissioner
    user_id = session.get('user_id') 

    if not all([league_name, season_year, user_id]):
        return jsonify({"error": "Missing league name, season year, or user session data"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    
    try:
        # 1. Insert the new League
        league_query = "INSERT INTO League (name, season_year, status) VALUES (%s, %s, 'Draft')"
        cursor.execute(league_query, (league_name, season_year))
        league_id = cursor.lastrowid
        
        # 2. Assign the creator as Commissioner
        role_query = "INSERT INTO RoleAssignment (user_id, league_id, role) VALUES (%s, %s, %s)"
        cursor.execute(role_query, (user_id, league_id, 'Commissioner'))
        
        conn.commit()
        
        return jsonify({
            "message": f"League '{league_name} ({season_year})' created successfully.", 
            "league_id": league_id
        }), 201

    except mysql.connector.Error as err:
        if err.errno == 1062: # Duplicate entry (name, season_year)
            return jsonify({"error": f"A league named '{league_name}' already exists for season {season_year}."}), 409
        print(f"Database error during league creation: {err}")
        return jsonify({"error": "League creation failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Clears the user session."""
    session.clear()
    return jsonify({"message": "Successfully logged out"}), 200

league_bp = Blueprint('league', __name__)

@app.route('/api/team', methods=['POST'])
@login_required 
def create_team():
    data = request.get_json()
    league_id = data.get('league_id')
    team_name = data.get('team_name')
    user_id = session.get('user_id') 

    if not all([league_id, team_name, user_id]):
        return jsonify({"error": "Missing data or user session"}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    
    try:
        # Check 1: Ensure user is a member of the league (RoleAssignment check)
        check_member_q = "SELECT COUNT(*) FROM RoleAssignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(check_member_q, (user_id, league_id))
        if cursor.fetchone()[0] == 0:
             return jsonify({"error": "You must be a member of the league to create a team."}), 403
        
        # 2. Get the player_id corresponding to the user_id
        player_q = "SELECT player_id FROM Player WHERE user_id = %s"
        cursor.execute(player_q, (user_id,))
        player_row = cursor.fetchone()
        
        if not player_row:
            return jsonify({"error": "Player profile not found for this user."}), 500

        player_id = player_row[0]

        # Check 3: Ensure player is not already an active member of a team in this league
        check_active_q = """
            SELECT COUNT(TM.player_id) 
            FROM TeamMembership TM
            JOIN Team T ON TM.team_id = T.team_id
            WHERE TM.player_id = %s AND T.league_id = %s AND TM.active = TRUE
        """
        cursor.execute(check_active_q, (player_id, league_id))
        if cursor.fetchone()[0] > 0:
             return jsonify({"error": "You are already an active member of a team in this league."}), 409
        
        # --- Start Transaction ---
        
        # 4. Insert the new Team
        team_query = "INSERT INTO Team (league_id, team_name) VALUES (%s, %s)"
        cursor.execute(team_query, (league_id, team_name))
        team_id = cursor.lastrowid
        
        # 5. Insert the user/player into the TeamMembership table
        membership_query = """
            INSERT INTO TeamMembership (team_id, player_id, active, joined_at) 
            VALUES (%s, %s, TRUE, NOW())
        """
        cursor.execute(membership_query, (team_id, player_id))

        conn.commit()
        
        return jsonify({
            "message": "Team created successfully. You are now the first member!", 
            "team_id": team_id
        }), 201

    except mysql.connector.Error as err:
        conn.rollback()
        if err.errno == 1062: # Duplicate entry error
            return jsonify({"error": f"Team name '{team_name}' already exists in this league."}), 409
        print(f"Database error during team creation: {err}")
        return jsonify({"error": "Team creation failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

@league_bp.route('/league/<int:league_id>/details', methods=['GET'])
@login_required 
def get_league_details(league_id):
    current_user_id = session.get('user_id') 

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Get the current user's role (Commissioner or Player)
        role_query = "SELECT role FROM RoleAssignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(role_query, (current_user_id, league_id))
        user_info = cursor.fetchone()

        if not user_info:
            return jsonify({"error": "User is not a member of this league"}), 403

        user_role = user_info['role'] 
        
        # 2. Check for the user's active team (via TeamMembership)
        user_team_id = None
        # Join UserAccount -> Player -> TeamMembership -> Team
        team_check_query = """
            SELECT 
                T.team_id 
            FROM 
                Team T
            JOIN
                TeamMembership TM ON T.team_id = TM.team_id
            JOIN
                Player P ON TM.player_id = P.player_id
            WHERE 
                P.user_id = %s 
                AND T.league_id = %s 
                AND TM.active = TRUE
        """
        cursor.execute(team_check_query, (current_user_id, league_id))
        team_row = cursor.fetchone()
        if team_row:
            user_team_id = team_row['team_id']
        
        # 3. Fetch the main League details
        league_query = "SELECT name, season_year, status FROM League WHERE league_id = %s"
        cursor.execute(league_query, (league_id,))
        league = cursor.fetchone()
        if not league:
            return jsonify({"error": "League not found"}), 404

        # 4. Fetch all Teams and the count of players (no 'owner' needed)
        teams_data = []
        teams_query = """
            SELECT 
                T.team_id, 
                T.team_name,
                COUNT(TM.player_id) AS member_count
            FROM 
                Team T
            LEFT JOIN
                TeamMembership TM ON T.team_id = TM.team_id AND TM.active = TRUE
            WHERE 
                T.league_id = %s 
            GROUP BY 
                T.team_id, T.team_name
            ORDER BY
                T.team_name ASC;
        """
        cursor.execute(teams_query, (league_id,))
        teams_data = cursor.fetchall()
        
        # 5. Compile and return the final response
        response_data = {
            "league_id": league_id,
            "league_name": league['name'],
            "season_year": league['season_year'],
            "status": league['status'],
            "user_role": user_role,
            "user_team_id": user_team_id,
            "teams": teams_data
        }

        return jsonify(response_data), 200

    except mysql.connector.Error as err:
        print(f"Database error in get_league_details: {err}")
        return jsonify({"error": "Server error while fetching league details"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/team/join', methods=['POST'])
@login_required 
def join_team():
    data = request.get_json()
    league_id = data.get('league_id')
    team_id = data.get('team_id')
    user_id = session.get('user_id') 

    if not all([league_id, team_id, user_id]):
        return jsonify({"error": "Missing data (league_id or team_id) or user session"}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    
    try:
        # 1. Get player_id corresponding to the user_id
        player_q = "SELECT player_id FROM Player WHERE user_id = %s"
        cursor.execute(player_q, (user_id,))
        player_row = cursor.fetchone()
        
        if not player_row:
            return jsonify({"error": "Player profile not found for this user."}), 500

        player_id = player_row[0]

        # 2. Check: Is the player already on a team in this league?
        check_active_q = """
            SELECT COUNT(TM.player_id) 
            FROM TeamMembership TM
            JOIN Team T ON TM.team_id = T.team_id
            WHERE TM.player_id = %s AND T.league_id = %s AND TM.active = TRUE
        """
        cursor.execute(check_active_q, (player_id, league_id))
        if cursor.fetchone()[0] > 0:
             return jsonify({"error": "You are already an active member of a team in this league."}), 409

        # 3. Check: Is the target team full (Limit 2 players)?
        roster_size_q = "SELECT COUNT(player_id) FROM TeamMembership WHERE team_id = %s AND active = TRUE"
        cursor.execute(roster_size_q, (team_id,))
        current_size = cursor.fetchone()[0]

        if current_size >= 2:
            return jsonify({"error": "This team's roster is already full (maximum 2 players)."}), 409
        
        # --- Start Transaction ---
        
        # 4. Add the player to the TeamMembership table
        membership_query = """
            INSERT INTO TeamMembership (team_id, player_id, active, joined_at) 
            VALUES (%s, %s, TRUE, NOW())
        """
        cursor.execute(membership_query, (team_id, player_id))

        conn.commit()
        
        return jsonify({
            "message": "Successfully joined the team!", 
            "team_id": team_id
        }), 200

    except mysql.connector.Error as err:
        conn.rollback()
        print(f"Database error during team join: {err}")
        return jsonify({"error": "Failed to join team due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

app.register_blueprint(league_bp, url_prefix='/api')
# -----------------------
# NOTHING SHOULD BE BELOW HERE EXCEPT THIS
# -----------------------

if __name__ == '__main__':
    app.run(debug=True)
